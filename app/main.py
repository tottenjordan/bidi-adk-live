# app/main.py
"""FastAPI application for ADK bidi-streaming with WebSocket."""

import asyncio
import base64
import json
import logging
import sys
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

APP_NAME = "home-appliance-detector"

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
        """Stream agent events back to the client."""
        try:
            async for event in runner.run_live(
                session_id=session_id,
                user_id=user_id,
                live_request_queue=live_request_queue,
                run_config=run_config,
            ):
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
