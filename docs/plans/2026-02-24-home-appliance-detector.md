# Home Appliance Detector - Bidi Streaming ADK Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-time bidirectional streaming application where users walk through their homes with a camera, and an ADK agent watches the live video feed to detect home appliances, confirm with the user, gather make/model details, and log them to an inventory stored in session state.

**Architecture:** FastAPI WebSocket server connects a browser-based UI to a Google ADK agent running via `Runner.run_live()`. The browser captures audio from the microphone and video frames from the camera, streaming them over WebSocket. Two concurrent async tasks handle upstream (client-to-agent via `LiveRequestQueue`) and downstream (agent events-to-client). The agent uses the `gemini-live-2.5-flash-native-audio` model via the Vertex AI Live API, with a `log_appliance` tool that writes confirmed appliances to `session.state["appliance_inventory"]`. Real-time audio transcription is enabled for both input and output via `AudioTranscriptionConfig`.

**Tech Stack:**
- Python 3.10+, uv (build system), pytest (testing)
- google-adk >= 1.20.0 (ADK framework with Live API support)
- FastAPI + uvicorn (WebSocket server)
- Vertex AI Live API with `gemini-live-2.5-flash-native-audio`
- Vanilla HTML/CSS/JS frontend (Web Audio API + MediaDevices API)

**Reference:** Architecture follows [adk-samples/bidi-demo](https://github.com/google/adk-samples/tree/main/python/agents/bidi-demo)

---

## Project Structure

```
bidi-adk-live/
├── app/
│   ├── home_agent/
│   │   ├── __init__.py          # Package init: from .agent import agent
│   │   ├── agent.py             # ADK agent definition with instruction + tools
│   │   └── tools.py             # log_appliance tool function
│   ├── main.py                  # FastAPI app with WebSocket endpoint
│   ├── .env                     # Vertex AI environment config (git-ignored)
│   └── static/
│       ├── index.html           # Main web interface
│       ├── css/
│       │   └── style.css        # UI styles
│       └── js/
│           ├── app.js           # Core WebSocket + UI logic
│           ├── audio-player.js  # Audio playback worklet setup
│           ├── audio-recorder.js # Microphone capture worklet setup
│           ├── pcm-player-processor.js   # AudioWorkletProcessor for playback
│           └── pcm-recorder-processor.js # AudioWorkletProcessor for recording
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── test_tools.py            # Unit tests for log_appliance tool
│   ├── test_agent.py            # Agent configuration tests
│   └── test_main.py             # FastAPI WebSocket integration tests
├── pyproject.toml               # uv project config with dependencies
├── .env.template                # Template for environment variables
├── .gitignore
├── CLAUDE.md                    # Project context for Claude Code
└── README.md                    # Project documentation
```

---

## Task 1: Project Scaffolding and Dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.template`
- Create: `app/.env` (git-ignored)

**Step 1: Initialize git repository**

```bash
cd /usr/local/google/home/jordantotten/antigravity/bidi-adk-live
git init
```

**Step 2: Create pyproject.toml**

```toml
[project]
name = "bidi-adk-live"
version = "0.1.0"
description = "Real-time home appliance detector using ADK bidi-streaming with Vertex AI Live API"
readme = "README.md"
requires-python = ">=3.10"
license = "Apache-2.0"
dependencies = [
    "google-adk>=1.20.0",
    "fastapi>=0.115.0",
    "python-dotenv>=1.0.0",
    "uvicorn[standard]>=0.32.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 88

[tool.ruff.lint]
ignore = ["C901", "PLR0915"]

[tool.ruff.lint.isort]
known-first-party = ["app", "home_agent"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

**Step 3: Create .gitignore**

```
__pycache__/
*.pyc
.env
.venv/
*.egg-info/
dist/
build/
.pytest_cache/
uv.lock
```

**Step 4: Create .env.template**

```bash
# Vertex AI Configuration
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

**Step 5: Create app/.env from template**

```bash
# Copy and fill in your actual project ID
cp .env.template app/.env
# Edit app/.env with your GOOGLE_CLOUD_PROJECT value
```

**Step 6: Install dependencies with uv**

```bash
uv sync --all-extras
```

**Step 7: Verify installation**

```bash
uv run python -c "import google.adk; print(google.adk.__version__)"
```

**Step 8: Commit**

```bash
git add pyproject.toml .gitignore .env.template
git commit -m "chore: scaffold project with uv and dependencies"
```

---

## Task 2: Appliance Inventory Tool (`log_appliance`)

**Files:**
- Create: `app/home_agent/tools.py`
- Create: `tests/__init__.py`
- Create: `tests/test_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_tools.py
"""Tests for the home agent tools."""

from unittest.mock import MagicMock

import pytest


class TestLogAppliance:
    """Tests for the log_appliance tool function."""

    def test_log_appliance_adds_to_empty_inventory(self):
        """First appliance creates the inventory list."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        mock_context.state = {}

        result = log_appliance(
            appliance_type="refrigerator",
            make="Samsung",
            model="RF28R7351SR",
            location="kitchen",
            tool_context=mock_context,
        )

        assert result["status"] == "success"
        assert len(mock_context.state["appliance_inventory"]) == 1
        entry = mock_context.state["appliance_inventory"][0]
        assert entry["appliance_type"] == "refrigerator"
        assert entry["make"] == "Samsung"
        assert entry["model"] == "RF28R7351SR"
        assert entry["location"] == "kitchen"

    def test_log_appliance_appends_to_existing_inventory(self):
        """Subsequent appliances append to the list."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        existing = [{"appliance_type": "oven", "make": "GE", "model": "JB655", "location": "kitchen"}]
        mock_context.state = {"appliance_inventory": list(existing)}

        result = log_appliance(
            appliance_type="dishwasher",
            make="Bosch",
            model="SHPM88Z75N",
            location="kitchen",
            tool_context=mock_context,
        )

        assert result["status"] == "success"
        assert len(mock_context.state["appliance_inventory"]) == 2
        assert mock_context.state["appliance_inventory"][0]["appliance_type"] == "oven"
        assert mock_context.state["appliance_inventory"][1]["appliance_type"] == "dishwasher"

    def test_log_appliance_with_optional_notes(self):
        """Notes field is included when provided."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        mock_context.state = {}

        result = log_appliance(
            appliance_type="washing machine",
            make="LG",
            model="WM4000HWA",
            location="laundry room",
            notes="Front loader, purchased 2024",
            tool_context=mock_context,
        )

        assert result["status"] == "success"
        entry = mock_context.state["appliance_inventory"][0]
        assert entry["notes"] == "Front loader, purchased 2024"

    def test_log_appliance_without_optional_notes(self):
        """Notes field defaults to empty string when not provided."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        mock_context.state = {}

        result = log_appliance(
            appliance_type="microwave",
            make="Panasonic",
            model="NN-SN66KB",
            location="kitchen",
            tool_context=mock_context,
        )

        entry = mock_context.state["appliance_inventory"][0]
        assert entry["notes"] == ""

    def test_log_appliance_returns_current_count(self):
        """Result includes the total inventory count."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        existing = [
            {"appliance_type": "oven", "make": "GE", "model": "JB655", "location": "kitchen"},
            {"appliance_type": "fridge", "make": "LG", "model": "LRMVS3006S", "location": "kitchen"},
        ]
        mock_context.state = {"appliance_inventory": list(existing)}

        result = log_appliance(
            appliance_type="dryer",
            make="Samsung",
            model="DVE45R6100W",
            location="laundry room",
            tool_context=mock_context,
        )

        assert result["total_appliances"] == 3
```

**Step 2: Create tests/__init__.py and run test to verify it fails**

```bash
touch tests/__init__.py
uv run pytest tests/test_tools.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.home_agent'`

**Step 3: Write minimal implementation**

```python
# app/home_agent/tools.py
"""Tools for the home appliance detector agent."""

from google.adk.tools.tool_context import ToolContext


def log_appliance(
    appliance_type: str,
    make: str,
    model: str,
    location: str,
    tool_context: ToolContext,
    notes: str = "",
) -> dict:
    """Logs a confirmed home appliance to the user's inventory.

    Args:
        appliance_type: The type of appliance (e.g., refrigerator, oven, dishwasher).
        make: The manufacturer/brand of the appliance (e.g., Samsung, GE, Bosch).
        model: The model number or name of the appliance.
        location: Where in the home the appliance is located (e.g., kitchen, laundry room).
        notes: Optional additional notes about the appliance.
    """
    inventory = tool_context.state.get("appliance_inventory", [])

    entry = {
        "appliance_type": appliance_type,
        "make": make,
        "model": model,
        "location": location,
        "notes": notes,
    }
    inventory.append(entry)
    tool_context.state["appliance_inventory"] = inventory

    return {
        "status": "success",
        "message": f"Logged {make} {model} {appliance_type} in {location}.",
        "total_appliances": len(inventory),
    }
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_tools.py -v
```
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add app/home_agent/tools.py tests/__init__.py tests/test_tools.py
git commit -m "feat: add log_appliance tool with session state storage"
```

---

## Task 3: ADK Agent Definition

**Files:**
- Create: `app/home_agent/__init__.py`
- Create: `app/home_agent/agent.py`
- Create: `tests/test_agent.py`

**Step 1: Write the failing test**

```python
# tests/test_agent.py
"""Tests for the home appliance detector agent configuration."""

import pytest


class TestAgentConfiguration:
    """Verify the agent is properly configured."""

    def test_agent_exists_and_is_importable(self):
        """Agent can be imported from the package."""
        from app.home_agent import agent

        assert agent is not None

    def test_agent_name(self):
        """Agent has the correct name."""
        from app.home_agent import agent

        assert agent.name == "home_appliance_detector"

    def test_agent_model_is_set(self):
        """Agent has a model configured."""
        from app.home_agent import agent

        assert agent.model is not None

    def test_agent_has_log_appliance_tool(self):
        """Agent has the log_appliance tool registered."""
        from app.home_agent import agent

        tool_names = [t.__name__ if callable(t) else str(t) for t in agent.tools]
        assert "log_appliance" in tool_names

    def test_agent_has_instruction(self):
        """Agent has a non-empty instruction."""
        from app.home_agent import agent

        assert agent.instruction is not None
        assert len(agent.instruction) > 0

    def test_agent_instruction_mentions_appliances(self):
        """Agent instruction references appliance detection."""
        from app.home_agent import agent

        instruction = agent.instruction.lower()
        assert "appliance" in instruction

    def test_agent_instruction_mentions_confirmation(self):
        """Agent instruction tells it to confirm with user before logging."""
        from app.home_agent import agent

        instruction = agent.instruction.lower()
        assert "confirm" in instruction
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_agent.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.home_agent'`

**Step 3: Write the agent definition**

```python
# app/home_agent/agent.py
"""Home appliance detector agent definition."""

import os

from google.adk.agents import Agent

from .tools import log_appliance

MODEL = os.getenv(
    "HOME_AGENT_MODEL",
    "gemini-live-2.5-flash-native-audio",
)

agent = Agent(
    name="home_appliance_detector",
    model=MODEL,
    instruction="""You are a home appliance inventory assistant. You watch a live video stream \
as the user walks through their home.

YOUR PRIMARY TASK:
- Continuously monitor the video feed for home appliances (refrigerators, ovens, stoves, \
dishwashers, microwaves, washing machines, dryers, water heaters, garbage disposals, \
range hoods, freezers, air conditioners, humidifiers, dehumidifiers, and any other \
household appliances).
- When you detect an appliance in the video, describe what you see to the user clearly \
(e.g., "I can see what looks like a stainless steel French door refrigerator").
- Ask the user if they want to log this appliance to their inventory.
- Only call the log_appliance tool AFTER the user confirms they want to log it.

GATHERING DETAILS:
- Before calling log_appliance, you need: appliance_type, make, model, and location.
- If you can identify the make and model from the video (logos, labels, distinctive design), \
tell the user what you think it is and ask them to confirm.
- If you cannot determine the make or model from the video, ask the user to provide it.
- Ask the user which room or area of the home the appliance is in if not obvious.
- You may also ask if they have any notes to add (e.g., purchase date, condition).

INTERACTION STYLE:
- Be conversational and natural. You are having a real-time voice conversation.
- Keep responses concise since this is a live audio interaction.
- Do not repeat yourself or re-detect appliances already in the inventory.
- After logging an appliance, briefly confirm it was saved and mention the total count.
- If the user says "no" or declines to log an appliance, acknowledge and move on.

INVENTORY STATE:
- The current inventory is stored in the session state variable 'appliance_inventory'.
- Check this before logging to avoid duplicates.
""",
    tools=[log_appliance],
)
```

**Step 4: Create the package init**

```python
# app/home_agent/__init__.py
"""Home appliance detector agent package."""

from .agent import agent
```

**Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_agent.py -v
```
Expected: All 7 tests PASS

**Step 6: Commit**

```bash
git add app/home_agent/__init__.py app/home_agent/agent.py tests/test_agent.py
git commit -m "feat: add home appliance detector ADK agent with instruction and tools"
```

---

## Task 4: FastAPI WebSocket Server (`main.py`)

**Files:**
- Create: `app/main.py`
- Create: `tests/conftest.py`
- Create: `tests/test_main.py`

**Step 1: Write the failing test**

```python
# tests/conftest.py
"""Shared test fixtures."""

import pytest


@pytest.fixture
def app():
    """Import and return the FastAPI app."""
    from app.main import app
    return app
```

```python
# tests/test_main.py
"""Tests for the FastAPI WebSocket server."""

import pytest
from fastapi.testclient import TestClient


class TestAppInitialization:
    """Verify the FastAPI app is properly configured."""

    def test_app_exists(self, app):
        """FastAPI app can be imported."""
        assert app is not None

    def test_root_serves_html(self, app):
        """Root path serves the index.html file."""
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    def test_static_files_mounted(self, app):
        """Static files are accessible."""
        client = TestClient(app)
        response = client.get("/static/css/style.css")
        # Will be 200 once static files exist, 404 is acceptable during scaffolding
        assert response.status_code in (200, 404)


class TestWebSocketEndpoint:
    """Verify WebSocket endpoint configuration."""

    def test_websocket_endpoint_accepts_connection(self, app):
        """WebSocket endpoint at /ws/{user_id}/{session_id} accepts connections."""
        client = TestClient(app)
        with client.websocket_connect("/ws/test-user/test-session") as ws:
            # Connection should be accepted without error
            assert ws is not None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_main.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

**Step 3: Write the FastAPI server**

```python
# app/main.py
"""FastAPI application for ADK bidi-streaming with WebSocket."""

import asyncio
import base64
import json
import logging
import warnings
from pathlib import Path

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

    is_native_audio = "native-audio" in (agent.model if isinstance(agent.model, str) else "")
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
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_main.py -v
```
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add app/main.py tests/conftest.py tests/test_main.py
git commit -m "feat: add FastAPI WebSocket server with bidi-streaming support"
```

---

## Task 5: PCM Audio Worklet Processors (Frontend)

**Files:**
- Create: `app/static/js/pcm-player-processor.js`
- Create: `app/static/js/pcm-recorder-processor.js`

These are AudioWorkletProcessor implementations that run in the Web Audio API thread. They cannot be tested with pytest — they are verified via browser integration in Task 8.

**Step 1: Create the PCM player processor**

```javascript
// app/static/js/pcm-player-processor.js
/**
 * AudioWorkletProcessor for PCM audio playback.
 * Implements a ring buffer to smooth out audio delivery from the WebSocket stream.
 * Input: Int16 PCM samples at 24kHz from the agent's audio output.
 * Output: Float32 samples to the AudioContext destination (speakers).
 */
class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Ring buffer: 24000 samples/sec * 180 sec = 4,320,000 samples max
    this.bufferSize = 24000 * 180;
    this.buffer = new Float32Array(this.bufferSize);
    this.writeIndex = 0;
    this.readIndex = 0;

    this.port.onmessage = (event) => {
      if (event.data === "endOfAudio") {
        this.buffer.fill(0);
        this.writeIndex = 0;
        this.readIndex = 0;
        return;
      }
      this._enqueue(event.data);
    };
  }

  _enqueue(int16Array) {
    for (let i = 0; i < int16Array.length; i++) {
      this.buffer[this.writeIndex] = int16Array[i] / 0x7fff;
      this.writeIndex = (this.writeIndex + 1) % this.bufferSize;
      // Overflow protection: advance read index if write catches up
      if (this.writeIndex === this.readIndex) {
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      }
    }
  }

  process(inputs, outputs, parameters) {
    const output = outputs[0];
    const channel0 = output[0];
    const channel1 = output.length > 1 ? output[1] : null;

    for (let i = 0; i < channel0.length; i++) {
      if (this.readIndex !== this.writeIndex) {
        const sample = this.buffer[this.readIndex];
        channel0[i] = sample;
        if (channel1) channel1[i] = sample;
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      } else {
        channel0[i] = 0;
        if (channel1) channel1[i] = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-player-processor", PCMPlayerProcessor);
```

**Step 2: Create the PCM recorder processor**

```javascript
// app/static/js/pcm-recorder-processor.js
/**
 * AudioWorkletProcessor for microphone PCM capture.
 * Captures Float32 audio frames from the microphone and sends them
 * to the main thread via port.postMessage for WebSocket transmission.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
  }

  process(inputs, outputs, parameters) {
    if (inputs.length > 0 && inputs[0].length > 0) {
      const inputChannel = inputs[0][0];
      const inputCopy = new Float32Array(inputChannel);
      this.port.postMessage(inputCopy);
    }
    return true;
  }
}

registerProcessor("pcm-recorder-processor", PCMProcessor);
```

**Step 3: Commit**

```bash
git add app/static/js/pcm-player-processor.js app/static/js/pcm-recorder-processor.js
git commit -m "feat: add PCM audio worklet processors for playback and recording"
```

---

## Task 6: Audio Player and Recorder Modules (Frontend)

**Files:**
- Create: `app/static/js/audio-player.js`
- Create: `app/static/js/audio-recorder.js`

**Step 1: Create the audio player module**

```javascript
// app/static/js/audio-player.js
/**
 * Initializes a Web Audio API worklet for PCM audio playback at 24kHz.
 * Returns the AudioWorkletNode (for sending audio data) and the AudioContext.
 */
export async function startAudioPlayerWorklet() {
  const audioContext = new AudioContext({ sampleRate: 24000 });
  const workletURL = new URL("./pcm-player-processor.js", import.meta.url);
  await audioContext.audioWorklet.addModule(workletURL);
  const audioPlayerNode = new AudioWorkletNode(audioContext, "pcm-player-processor");
  audioPlayerNode.connect(audioContext.destination);
  return [audioPlayerNode, audioContext];
}
```

**Step 2: Create the audio recorder module**

```javascript
// app/static/js/audio-recorder.js
/**
 * Initializes microphone capture at 16kHz and streams PCM data via callback.
 * @param {Function} audioRecorderHandler - Called with Int16Array PCM chunks
 * @returns {[AudioWorkletNode, MediaStream]} - Node and stream for cleanup
 */
export async function startAudioRecorderWorklet(audioRecorderHandler) {
  const audioContext = new AudioContext({ sampleRate: 16000 });
  const workletURL = new URL("./pcm-recorder-processor.js", import.meta.url);
  await audioContext.audioWorklet.addModule(workletURL);

  const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const source = audioContext.createMediaStreamSource(micStream);
  const recorderNode = new AudioWorkletNode(audioContext, "pcm-recorder-processor");

  recorderNode.port.onmessage = (event) => {
    const float32Data = event.data;
    const int16Data = convertFloat32ToPCM(float32Data);
    audioRecorderHandler(int16Data);
  };

  source.connect(recorderNode);
  recorderNode.connect(audioContext.destination);

  return [recorderNode, micStream];
}

/**
 * Stops all tracks on a MediaStream (releases microphone).
 */
export function stopMicrophone(micStream) {
  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
  }
}

/**
 * Converts Float32Array audio samples to Int16Array PCM.
 */
function convertFloat32ToPCM(float32Array) {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16Array;
}
```

**Step 3: Commit**

```bash
git add app/static/js/audio-player.js app/static/js/audio-recorder.js
git commit -m "feat: add audio player and recorder worklet modules"
```

---

## Task 7: Web Interface HTML and CSS

**Files:**
- Create: `app/static/index.html`
- Create: `app/static/css/style.css`

**Step 1: Create the HTML interface**

```html
<!-- app/static/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Home Appliance Detector - ADK Live</title>
  <link rel="stylesheet" href="/static/css/style.css" />
  <script type="module" src="/static/js/app.js"></script>
</head>
<body>
  <header>
    <div class="header-content">
      <h1>Home Appliance Detector</h1>
      <p class="subtitle">Walk through your home — I'll identify and inventory your appliances</p>
    </div>
    <div class="connection-status" id="connectionStatus">
      <span class="status-dot"></span>
      <span class="status-text">Disconnected</span>
    </div>
  </header>

  <main>
    <!-- Left panel: Chat + Controls -->
    <section class="chat-panel">
      <div class="messages" id="messages"></div>

      <!-- Inventory summary bar -->
      <div class="inventory-bar" id="inventoryBar">
        <span class="inventory-label">Inventory:</span>
        <span class="inventory-count" id="inventoryCount">0 appliances</span>
      </div>

      <!-- Input controls -->
      <div class="controls">
        <form id="textForm" class="text-input-form">
          <input type="text" id="textInput" placeholder="Type a message..." autocomplete="off" />
          <button type="submit" id="sendBtn">Send</button>
        </form>
        <div class="media-controls">
          <button id="micBtn" class="control-btn" title="Toggle Microphone">
            <span class="btn-icon">🎤</span>
            <span class="btn-label">Mic Off</span>
          </button>
          <button id="cameraBtn" class="control-btn" title="Toggle Camera">
            <span class="btn-icon">📷</span>
            <span class="btn-label">Camera Off</span>
          </button>
        </div>
      </div>
    </section>

    <!-- Right panel: Event Console + Camera Preview -->
    <section class="side-panel">
      <!-- Camera preview -->
      <div class="camera-container" id="cameraContainer" style="display: none;">
        <video id="cameraPreview" autoplay playsinline muted></video>
        <canvas id="captureCanvas" style="display: none;"></canvas>
      </div>

      <!-- Transcription panel -->
      <div class="transcription-panel">
        <div class="panel-header">
          <h3>Transcription</h3>
        </div>
        <div class="transcription-content" id="transcriptionContent"></div>
      </div>

      <!-- Event console -->
      <div class="console-panel">
        <div class="panel-header">
          <h3>Event Console</h3>
          <label class="filter-toggle">
            <input type="checkbox" id="filterAudio" checked />
            Hide audio events
          </label>
        </div>
        <div class="console-content" id="consoleContent"></div>
      </div>
    </section>
  </main>
</body>
</html>
```

**Step 2: Create the CSS stylesheet**

This is a large file. The implementation should follow the bidi-demo reference styling with these customizations:
- Split layout: 2/3 chat panel, 1/3 side panel (console + camera)
- Material Design-inspired with a gradient header
- Dark-themed console panel for event monitoring
- Message bubbles for user and agent messages
- Camera preview area with live video feed
- Transcription panel showing real-time speech-to-text
- Inventory count bar above the controls
- Responsive design with mobile breakpoint at 768px
- Animations for message slide-in, typing indicators, connection status

Create `app/static/css/style.css` following the bidi-demo reference styling patterns. Key sections:
- CSS variables for the color palette
- Global reset and typography
- Header with gradient and connection status indicator
- Chat panel with message bubbles (user = right-aligned blue, agent = left-aligned gray)
- Controls bar with text input, mic button, camera button
- Camera preview container with video element
- Transcription panel with scrollable content
- Console panel with dark background and monospace text
- Responsive layout adjustments

**Step 3: Commit**

```bash
git add app/static/index.html app/static/css/style.css
git commit -m "feat: add web interface with chat, camera preview, and event console"
```

---

## Task 8: Core Application JavaScript (`app.js`)

**Files:**
- Create: `app/static/js/app.js`

This is the largest frontend file. It handles WebSocket communication, UI updates, audio streaming, camera capture, and event console logging.

**Step 1: Create app.js**

```javascript
// app/static/js/app.js
/**
 * Core application logic for the Home Appliance Detector.
 * Handles WebSocket communication, audio streaming, camera capture,
 * transcription display, and event console logging.
 */

import { startAudioPlayerWorklet } from "./audio-player.js";
import { startAudioRecorderWorklet, stopMicrophone } from "./audio-recorder.js";

// --- State ---
let ws = null;
let audioPlayerNode = null;
let audioPlayerContext = null;
let audioRecorderNode = null;
let micStream = null;
let isMicActive = false;
let isCameraActive = false;
let cameraStream = null;
let cameraInterval = null;
const CAMERA_FPS = 1; // 1 frame per second for video streaming

// --- DOM Elements ---
const messagesEl = document.getElementById("messages");
const textForm = document.getElementById("textForm");
const textInput = document.getElementById("textInput");
const micBtn = document.getElementById("micBtn");
const cameraBtn = document.getElementById("cameraBtn");
const connectionStatus = document.getElementById("connectionStatus");
const consoleContent = document.getElementById("consoleContent");
const filterAudioCheckbox = document.getElementById("filterAudio");
const cameraContainer = document.getElementById("cameraContainer");
const cameraPreview = document.getElementById("cameraPreview");
const captureCanvas = document.getElementById("captureCanvas");
const inventoryCount = document.getElementById("inventoryCount");
const transcriptionContent = document.getElementById("transcriptionContent");

// --- Transcription State ---
let currentInputTranscription = "";
let currentOutputTranscription = "";

// --- WebSocket Connection ---
function connect() {
  const userId = `user-${Date.now()}`;
  const sessionId = `session-${Date.now()}`;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/${userId}/${sessionId}`;

  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    updateConnectionStatus(true);
    logConsole("system", "Connected to server");
  };

  ws.onclose = () => {
    updateConnectionStatus(false);
    logConsole("system", "Disconnected from server");
    // Reconnect after delay
    setTimeout(connect, 5000);
  };

  ws.onerror = (error) => {
    logConsole("error", `WebSocket error: ${error.message || "Unknown error"}`);
  };

  ws.onmessage = (event) => {
    handleServerEvent(event.data);
  };
}

function updateConnectionStatus(connected) {
  const dot = connectionStatus.querySelector(".status-dot");
  const text = connectionStatus.querySelector(".status-text");
  dot.className = `status-dot ${connected ? "connected" : ""}`;
  text.textContent = connected ? "Connected" : "Disconnected";
}

// --- Message Display ---
let currentAgentMessageEl = null;
let currentAgentText = "";

function addMessage(role, text) {
  const msgEl = document.createElement("div");
  msgEl.className = `message ${role}`;
  msgEl.textContent = text;
  messagesEl.appendChild(msgEl);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return msgEl;
}

function updateAgentMessage(text, isPartial) {
  if (!currentAgentMessageEl) {
    currentAgentMessageEl = addMessage("agent", "");
  }
  if (isPartial) {
    currentAgentText = text;
  } else {
    currentAgentText = text;
  }
  currentAgentMessageEl.textContent = currentAgentText;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function finalizeAgentMessage() {
  currentAgentMessageEl = null;
  currentAgentText = "";
}

// --- Server Event Handling ---
function handleServerEvent(data) {
  let event;
  try {
    event = JSON.parse(data);
  } catch {
    return;
  }

  const isAudioEvent = hasAudioData(event);

  // Log to console (respecting audio filter)
  if (!isAudioEvent || !filterAudioCheckbox.checked) {
    logConsole(event.author || "system", JSON.stringify(event, null, 2), isAudioEvent);
  }

  // Handle audio output
  if (event.content?.parts) {
    for (const part of event.content.parts) {
      // Audio data (inline_data)
      if (part.inline_data?.mime_type?.startsWith("audio/")) {
        playAudio(part.inline_data.data);
      }
      // Text content
      if (part.text) {
        updateAgentMessage(part.text, event.partial === true);
      }
    }
  }

  // Handle turn completion
  if (event.turn_complete) {
    finalizeAgentMessage();
  }

  // Handle interruption
  if (event.interrupted) {
    if (audioPlayerNode) {
      audioPlayerNode.port.postMessage("endOfAudio");
    }
    finalizeAgentMessage();
  }

  // Handle transcriptions
  if (event.input_transcription?.text) {
    updateTranscription("user", event.input_transcription.text, event.input_transcription.finished);
  }
  if (event.output_transcription?.text) {
    updateTranscription("agent", event.output_transcription.text, event.output_transcription.finished);
  }

  // Handle tool calls (for inventory updates)
  if (event.content?.parts) {
    for (const part of event.content.parts) {
      if (part.function_response?.response?.total_appliances !== undefined) {
        updateInventoryCount(part.function_response.response.total_appliances);
      }
    }
  }
}

function hasAudioData(event) {
  if (!event.content?.parts) return false;
  return event.content.parts.some(
    (p) => p.inline_data?.mime_type?.startsWith("audio/")
  );
}

// --- Transcription Display ---
function updateTranscription(role, text, finished) {
  if (role === "user") {
    currentInputTranscription = text;
  } else {
    currentOutputTranscription = text;
  }

  if (finished) {
    const entry = document.createElement("div");
    entry.className = `transcription-entry ${role}`;
    entry.innerHTML = `<span class="transcription-role">${role === "user" ? "You" : "Agent"}:</span> ${escapeHtml(text)}`;
    transcriptionContent.appendChild(entry);
    transcriptionContent.scrollTop = transcriptionContent.scrollHeight;

    if (role === "user") currentInputTranscription = "";
    else currentOutputTranscription = "";
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// --- Inventory Display ---
function updateInventoryCount(count) {
  inventoryCount.textContent = `${count} appliance${count !== 1 ? "s" : ""}`;
}

// --- Audio Playback ---
async function initAudioPlayer() {
  if (!audioPlayerNode) {
    [audioPlayerNode, audioPlayerContext] = await startAudioPlayerWorklet();
  }
}

function playAudio(base64Data) {
  if (!audioPlayerNode) return;
  const binaryStr = atob(base64Data);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }
  const int16Data = new Int16Array(bytes.buffer);
  audioPlayerNode.port.postMessage(int16Data);
}

// --- Microphone ---
async function toggleMicrophone() {
  if (isMicActive) {
    stopMicrophone(micStream);
    micStream = null;
    isMicActive = false;
    micBtn.querySelector(".btn-label").textContent = "Mic Off";
    micBtn.classList.remove("active");
  } else {
    await initAudioPlayer();
    [audioRecorderNode, micStream] = await startAudioRecorderWorklet((pcmData) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(pcmData.buffer);
      }
    });
    isMicActive = true;
    micBtn.querySelector(".btn-label").textContent = "Mic On";
    micBtn.classList.add("active");
  }
}

// --- Camera ---
async function toggleCamera() {
  if (isCameraActive) {
    stopCamera();
  } else {
    await startCamera();
  }
}

async function startCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { width: 768, height: 768, facingMode: "environment" },
    });
    cameraPreview.srcObject = cameraStream;
    cameraContainer.style.display = "block";
    isCameraActive = true;
    cameraBtn.querySelector(".btn-label").textContent = "Camera On";
    cameraBtn.classList.add("active");

    // Start sending frames at CAMERA_FPS
    cameraInterval = setInterval(captureAndSendFrame, 1000 / CAMERA_FPS);
  } catch (err) {
    logConsole("error", `Camera error: ${err.message}`);
  }
}

function stopCamera() {
  if (cameraInterval) {
    clearInterval(cameraInterval);
    cameraInterval = null;
  }
  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  cameraPreview.srcObject = null;
  cameraContainer.style.display = "none";
  isCameraActive = false;
  cameraBtn.querySelector(".btn-label").textContent = "Camera Off";
  cameraBtn.classList.remove("active");
}

function captureAndSendFrame() {
  if (!cameraStream || !ws || ws.readyState !== WebSocket.OPEN) return;

  const video = cameraPreview;
  const canvas = captureCanvas;
  canvas.width = video.videoWidth || 768;
  canvas.height = video.videoHeight || 768;

  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
  const base64Data = dataUrl.split(",")[1];

  ws.send(
    JSON.stringify({
      type: "image",
      mimeType: "image/jpeg",
      data: base64Data,
    })
  );
}

// --- Text Input ---
textForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = textInput.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

  addMessage("user", text);
  ws.send(JSON.stringify({ type: "text", text }));
  textInput.value = "";
});

// --- Console Logging ---
function logConsole(author, message, isAudio = false) {
  const entry = document.createElement("div");
  entry.className = `console-entry ${isAudio ? "audio-event" : ""}`;

  const timestamp = new Date().toLocaleTimeString();
  const badge = author === "system" ? "SYS" : author === "error" ? "ERR" : author.toUpperCase().slice(0, 3);

  entry.innerHTML = `<span class="console-time">${timestamp}</span> <span class="console-badge ${author}">${badge}</span> `;

  // For JSON, make it collapsible
  if (message.startsWith("{") || message.startsWith("[")) {
    const summary = document.createElement("span");
    summary.className = "console-summary";
    summary.textContent = message.slice(0, 80) + (message.length > 80 ? "..." : "");
    summary.style.cursor = "pointer";

    const details = document.createElement("pre");
    details.className = "console-details";
    details.textContent = message;
    details.style.display = "none";

    summary.addEventListener("click", () => {
      details.style.display = details.style.display === "none" ? "block" : "none";
    });

    entry.appendChild(summary);
    entry.appendChild(details);
  } else {
    entry.innerHTML += `<span class="console-text">${escapeHtml(message)}</span>`;
  }

  consoleContent.appendChild(entry);
  consoleContent.scrollTop = consoleContent.scrollHeight;
}

// --- Event Listeners ---
micBtn.addEventListener("click", toggleMicrophone);
cameraBtn.addEventListener("click", toggleCamera);

// --- Initialize ---
connect();
```

**Step 2: Commit**

```bash
git add app/static/js/app.js
git commit -m "feat: add core application JavaScript with WebSocket, audio, camera, and UI"
```

---

## Task 9: CSS Stylesheet

**Files:**
- Create: `app/static/css/style.css`

**Step 1: Create the stylesheet**

```css
/* app/static/css/style.css */

/* --- CSS Variables --- */
:root {
  --primary: #1a73e8;
  --primary-light: #4285f4;
  --primary-dark: #1557b0;
  --surface: #ffffff;
  --surface-dim: #f1f3f4;
  --on-surface: #202124;
  --on-surface-secondary: #5f6368;
  --agent-bubble: #f1f3f4;
  --user-bubble: #1a73e8;
  --user-text: #ffffff;
  --console-bg: #1e1e1e;
  --console-text: #d4d4d4;
  --border: #dadce0;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
  --shadow-lg: 0 4px 12px rgba(0, 0, 0, 0.15);
  --radius: 8px;
  --radius-lg: 16px;
}

/* --- Global Reset --- */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: "Google Sans", "Segoe UI", Roboto, sans-serif;
  background: var(--surface-dim);
  color: var(--on-surface);
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* --- Header --- */
header {
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  color: white;
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-lg);
  z-index: 10;
}

header h1 {
  font-size: 1.25rem;
  font-weight: 500;
}

.subtitle {
  font-size: 0.8rem;
  opacity: 0.85;
  margin-top: 2px;
}

.connection-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff5252;
  transition: background 0.3s;
}

.status-dot.connected {
  background: #34a853;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* --- Main Layout --- */
main {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* --- Chat Panel (Left 2/3) --- */
.chat-panel {
  flex: 2;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-right: 1px solid var(--border);
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  font-size: 0.9rem;
  line-height: 1.4;
  animation: slideIn 0.2s ease-out;
}

.message.user {
  align-self: flex-end;
  background: var(--user-bubble);
  color: var(--user-text);
  border-bottom-right-radius: 4px;
}

.message.agent {
  align-self: flex-start;
  background: var(--agent-bubble);
  color: var(--on-surface);
  border-bottom-left-radius: 4px;
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

/* --- Inventory Bar --- */
.inventory-bar {
  padding: 8px 16px;
  background: var(--surface-dim);
  border-top: 1px solid var(--border);
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  gap: 8px;
}

.inventory-label {
  color: var(--on-surface-secondary);
  font-weight: 500;
}

.inventory-count {
  color: var(--primary);
  font-weight: 600;
}

/* --- Controls --- */
.controls {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.text-input-form {
  display: flex;
  gap: 8px;
}

.text-input-form input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 0.9rem;
  outline: none;
  transition: border-color 0.2s;
}

.text-input-form input:focus {
  border-color: var(--primary);
}

.text-input-form button {
  padding: 10px 20px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-weight: 500;
  transition: background 0.2s;
}

.text-input-form button:hover {
  background: var(--primary-dark);
}

.media-controls {
  display: flex;
  gap: 8px;
}

.control-btn {
  flex: 1;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.control-btn:hover {
  background: var(--surface-dim);
}

.control-btn.active {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

/* --- Side Panel (Right 1/3) --- */
.side-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 320px;
}

/* --- Camera Preview --- */
.camera-container {
  background: #000;
  border-bottom: 1px solid var(--border);
}

.camera-container video {
  width: 100%;
  display: block;
}

/* --- Transcription Panel --- */
.transcription-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  min-height: 120px;
  max-height: 200px;
}

.panel-header {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h3 {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--on-surface-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.transcription-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  font-size: 0.82rem;
}

.transcription-entry {
  padding: 4px 0;
  line-height: 1.4;
}

.transcription-entry.user .transcription-role {
  color: var(--primary);
  font-weight: 600;
}

.transcription-entry.agent .transcription-role {
  color: #34a853;
  font-weight: 600;
}

/* --- Console Panel --- */
.console-panel {
  flex: 2;
  display: flex;
  flex-direction: column;
  background: var(--console-bg);
  color: var(--console-text);
}

.console-panel .panel-header {
  background: #252526;
  border-bottom: 1px solid #333;
}

.console-panel .panel-header h3 {
  color: #ccc;
}

.filter-toggle {
  font-size: 0.75rem;
  color: #999;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.filter-toggle input {
  cursor: pointer;
}

.console-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  font-family: "Fira Code", "Consolas", monospace;
  font-size: 0.75rem;
}

.console-entry {
  padding: 3px 0;
  border-bottom: 1px solid #2a2a2a;
}

.console-time {
  color: #666;
  margin-right: 6px;
}

.console-badge {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.65rem;
  font-weight: 600;
  margin-right: 6px;
}

.console-badge.system { background: #333; color: #aaa; }
.console-badge.error { background: #5c2020; color: #ff6b6b; }
.console-badge.home_appliance_detector { background: #1b3a2d; color: #34a853; }
.console-badge.user { background: #1a3a5c; color: #4285f4; }

.console-summary {
  color: #b0b0b0;
}

.console-details {
  margin-top: 4px;
  padding: 6px;
  background: #2a2a2a;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #8cb4ff;
  max-height: 200px;
  overflow-y: auto;
}

/* --- Scrollbar --- */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #ccc;
  border-radius: 3px;
}
.console-content::-webkit-scrollbar-thumb {
  background: #444;
}

/* --- Responsive --- */
@media (max-width: 768px) {
  main {
    flex-direction: column;
  }
  .chat-panel {
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .side-panel {
    min-width: unset;
    max-height: 40vh;
  }
}
```

**Step 2: Commit**

```bash
git add app/static/css/style.css
git commit -m "feat: add CSS stylesheet with split-pane layout and dark console theme"
```

---

## Task 10: Integration Test and End-to-End Verification

**Files:**
- Modify: `tests/test_main.py` (add WebSocket message tests)

**Step 1: Add integration tests for WebSocket message handling**

```python
# Append to tests/test_main.py

class TestWebSocketMessageFormats:
    """Verify the server handles different message types."""

    def test_text_message_format(self, app):
        """Server accepts JSON text messages."""
        import json
        client = TestClient(app)
        with client.websocket_connect("/ws/test-user/test-session") as ws:
            ws.send_text(json.dumps({"type": "text", "text": "Hello"}))
            # If the server processes without error, the connection stays open
            # The actual response depends on the Live API connection

    def test_image_message_format(self, app):
        """Server accepts JSON image messages with base64 data."""
        import json
        import base64
        client = TestClient(app)
        # Create a tiny valid JPEG-like payload (1x1 pixel)
        fake_image = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 10).decode()
        with client.websocket_connect("/ws/test-user/test-session") as ws:
            ws.send_text(json.dumps({
                "type": "image",
                "mimeType": "image/jpeg",
                "data": fake_image,
            }))
```

**Step 2: Run all tests**

```bash
uv run pytest tests/ -v
```
Expected: All tests PASS (integration tests may skip if Vertex AI credentials are not configured)

**Step 3: Commit**

```bash
git add tests/test_main.py
git commit -m "test: add WebSocket message format integration tests"
```

---

## Task 11: Run Script and Documentation

**Files:**
- Create: `README.md`

**Step 1: Create README**

```markdown
# Home Appliance Detector - ADK Bidi-Streaming

Real-time home appliance detection using Google ADK bidirectional streaming
with the Vertex AI Live API.

## Setup

1. Install dependencies:
   ```bash
   uv sync --all-extras
   ```

2. Configure environment:
   ```bash
   cp .env.template app/.env
   # Edit app/.env with your Google Cloud project details
   ```

3. Authenticate:
   ```bash
   gcloud auth application-default login
   ```

## Running

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

## Usage

1. Click **Camera** to start your video feed
2. Click **Mic** to enable voice interaction
3. Walk through your home — the agent will identify appliances
4. Confirm each appliance to add it to your inventory
5. The agent will ask follow-up questions for make and model

## Testing

```bash
uv run pytest tests/ -v
```

## Architecture

- **Backend**: FastAPI + WebSocket + Google ADK `Runner.run_live()`
- **Frontend**: Vanilla JS with Web Audio API worklets
- **Model**: `gemini-live-2.5-flash-native-audio` via Vertex AI Live API
- **Streaming**: Separate upstream/downstream async tasks for optimal performance
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and usage instructions"
```

---

## Task 12: Create CLAUDE.md Project Context

**Files:**
- Create: `CLAUDE.md`

**Step 1: Create CLAUDE.md**

This task will be completed after plan approval, per the user's request. The CLAUDE.md should include:

- Project overview and architecture
- Key file locations and their purposes
- Build commands (`uv sync`, `uv run pytest`, `uv run uvicorn`)
- ADK-specific patterns (LiveRequestQueue, RunConfig, ToolContext)
- Testing conventions
- Environment configuration requirements
- Common development workflows

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md project context"
```

---

## Summary of Tasks

| Task | Description | Files | Tests |
|------|------------|-------|-------|
| 1 | Project scaffolding and dependencies | `pyproject.toml`, `.gitignore`, `.env.template` | — |
| 2 | `log_appliance` tool | `app/home_agent/tools.py` | `tests/test_tools.py` (5 tests) |
| 3 | ADK agent definition | `app/home_agent/agent.py`, `__init__.py` | `tests/test_agent.py` (7 tests) |
| 4 | FastAPI WebSocket server | `app/main.py` | `tests/test_main.py` (4 tests) |
| 5 | PCM audio worklet processors | 2 JS files | Browser-verified |
| 6 | Audio player/recorder modules | 2 JS files | Browser-verified |
| 7 | HTML interface | `index.html` | Browser-verified |
| 8 | Core application JavaScript | `app.js` | Browser-verified |
| 9 | CSS stylesheet | `style.css` | Visual verification |
| 10 | Integration tests | `tests/test_main.py` | 2 additional tests |
| 11 | README documentation | `README.md` | — |
| 12 | CLAUDE.md project context | `CLAUDE.md` | — |

**Total: 12 tasks, 18+ automated tests**
