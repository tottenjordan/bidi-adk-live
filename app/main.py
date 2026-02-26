# app/main.py
"""FastAPI application for ADK bidi-streaming with WebSocket."""

import asyncio
import base64
import json
import logging
import os
import sys
import time
import warnings
from pathlib import Path

# Add the app directory to sys.path so that home_agent can be imported
# as a top-level package (matches the bidi-demo reference pattern).
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Load environment variables from .env file BEFORE importing agent
load_dotenv(Path(__file__).parent / ".env")

# Import agent after loading environment variables
# pylint: disable=wrong-import-position
from home_agent.agent import agent  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress Pydantic serialization warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

APP_NAME = os.getenv("APP_NAME", "home-appliance-detector")


# --- Phase 1: Application Initialization (once at startup) ---

app = FastAPI()

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

session_service = InMemorySessionService()

runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)


@app.get("/")
async def root():
    """Serve the main web interface."""
    return FileResponse(static_dir / "index.html")


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str, session_id: str):
    """Handle bidirectional streaming via WebSocket."""
    await websocket.accept()
    logger.info("WebSocket connected: user=%s session=%s", user_id, session_id)

    # --- Phase 2: Per-session setup ---
    session = await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )

    live_request_queue = LiveRequestQueue()

    is_native_audio = "native-audio" in (
        agent.model if isinstance(agent.model, str) else ""
    )
    response_modalities = ["AUDIO"] if is_native_audio else ["TEXT"]

    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=response_modalities,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        ),
        proactivity=types.ProactivityConfig(proactive_audio=True),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(
            handle=session.state.get("session_resumption_handle")
        ),
    )

    # --- Phase 3: Concurrent upstream/downstream tasks ---

    # Send an initial message to trigger the agent greeting
    live_request_queue.send_content(
        types.Content(
            role="user",
            parts=[types.Part(text="Hello, I just connected. Please greet me.")],
        )
    )

    async def upstream_task():
        """Receive client messages and queue them for the agent."""
        try:
            while True:
                message = await websocket.receive()

                if "bytes" in message:
                    audio_blob = types.Blob(
                        mime_type="audio/pcm;rate=16000",
                        data=message["bytes"],
                    )
                    live_request_queue.send_realtime(audio_blob)

                elif "text" in message:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "text":
                        content = types.Content(
                            parts=[types.Part(text=data["text"])]
                        )
                        live_request_queue.send_content(content)

                    elif msg_type == "image":
                        image_data = base64.b64decode(data["data"])
                        image_blob = types.Blob(
                            mime_type=data.get("mimeType", "image/jpeg"),
                            data=image_data,
                        )
                        live_request_queue.send_realtime(image_blob)

        except WebSocketDisconnect:
            logger.info("Client disconnected (upstream): user=%s", user_id)
        except Exception as e:
            logger.exception("Upstream error: %s", e)

    async def downstream_task():
        """Stream agent events back to the client.

        Audio data is sent as binary WebSocket frames for low-latency playback.
        All other event data (transcriptions, turn_complete, etc.) is sent as JSON text.
        """
        # --- Post-tool duplicate suppression state ---
        # The model sometimes speaks its tool-call confirmation twice in
        # back-to-back turns. We let the first confirmation through and
        # suppress the duplicate by tracking speech after the tool response:
        #   function_response seen → saw_tool_response = True
        #   model speaks (audio/transcription) → saw_post_tool_speech = True
        #   turn_complete (with speech delivered) → arm cooldown
        #   next speech within 5s → suppress until turn_complete
        saw_tool_response = False
        saw_post_tool_speech = False
        post_tool_cooldown_until = 0.0
        suppressing_turn = False

        try:
            async for event in runner.run_live(
                session_id=session_id,
                user_id=user_id,
                live_request_queue=live_request_queue,
                run_config=run_config,
            ):
                # --- Track function_response events ---
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.function_response:
                            saw_tool_response = True
                            saw_post_tool_speech = False

                # --- Track speech after tool response ---
                # Detect when the model actually speaks (audio or
                # transcription) after a tool response, so we only arm
                # the cooldown once the confirmation has been delivered.
                if saw_tool_response and not saw_post_tool_speech:
                    has_speech = (
                        event.output_transcription
                        or (
                            event.content
                            and event.content.parts
                            and any(
                                p.inline_data
                                and p.inline_data.mime_type
                                and p.inline_data.mime_type.startswith("audio/")
                                for p in event.content.parts
                            )
                        )
                    )
                    if has_speech:
                        saw_post_tool_speech = True

                # --- Post-tool cooldown activation ---
                # Only arm the cooldown after the model has both received
                # the tool response AND spoken its confirmation. This
                # prevents suppressing the confirmation itself.
                if event.turn_complete and saw_tool_response and saw_post_tool_speech:
                    post_tool_cooldown_until = time.monotonic() + 5.0
                    saw_tool_response = False
                    saw_post_tool_speech = False
                    logger.debug("Post-tool cooldown armed for 5s")

                # --- Suppress duplicate turn ---
                # If we're in cooldown and the model starts speaking again
                # (output audio or transcription), suppress the entire turn.
                if not suppressing_turn and time.monotonic() < post_tool_cooldown_until:
                    is_new_speech = (
                        event.output_transcription
                        or (
                            event.content
                            and event.content.parts
                            and any(
                                p.inline_data
                                and p.inline_data.mime_type
                                and p.inline_data.mime_type.startswith("audio/")
                                for p in event.content.parts
                            )
                        )
                    )
                    if is_new_speech:
                        suppressing_turn = True
                        logger.info("SUPPRESSING duplicate post-tool turn")

                if suppressing_turn:
                    if event.turn_complete:
                        suppressing_turn = False
                        post_tool_cooldown_until = 0.0
                        logger.info("Duplicate turn suppression ended (turn_complete)")
                    continue

                # Extract and send audio as binary frames
                if event.content and event.content.parts:
                    non_audio_parts = []
                    for part in event.content.parts:
                        if (
                            part.inline_data
                            and part.inline_data.mime_type
                            and part.inline_data.mime_type.startswith("audio/")
                        ):
                            # Send raw audio bytes as binary WebSocket frame
                            await websocket.send_bytes(part.inline_data.data)
                        else:
                            non_audio_parts.append(part)

                    # Replace parts with non-audio parts only
                    if non_audio_parts:
                        event.content.parts = non_audio_parts
                    else:
                        event.content = None

                # Only send JSON if the event has data the frontend needs:
                # content with non-audio parts, transcriptions, turn signals, etc.
                # Skip audio-only events that have no other useful fields.
                has_useful_data = (
                    event.content
                    or event.turn_complete
                    or event.interrupted
                    or event.input_transcription
                    or event.output_transcription
                )
                if has_useful_data:
                    event_json = event.model_dump_json(
                        exclude_none=True, by_alias=True
                    )
                    await websocket.send_text(event_json)
        except WebSocketDisconnect:
            logger.info("Client disconnected (downstream): user=%s", user_id)
        except Exception as e:
            logger.exception("Downstream error: %s", e)

    try:
        await asyncio.gather(upstream_task(), downstream_task())
    except Exception as e:
        logger.exception("Session error: %s", e)
    finally:
        live_request_queue.close()
        logger.info("Session closed: user=%s session=%s", user_id, session_id)
