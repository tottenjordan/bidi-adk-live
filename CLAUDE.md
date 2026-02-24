# CLAUDE.md - Project Context

## Project Overview

Home Appliance Detector: a real-time bidi-streaming application using Google ADK with the Vertex AI Live API. Users walk through their homes with a camera and microphone, and the agent watches the live video feed to detect home appliances, confirms with the user, gathers make/model details, and logs them to an inventory.

## Architecture

```
Browser (camera + mic) → WebSocket → FastAPI → ADK Runner.run_live() → Vertex AI Live API
                       ← WebSocket ← FastAPI ← ADK Events ←
```

- **Upstream**: Browser sends audio (binary PCM @ 16kHz), text (JSON), and images (JPEG base64 JSON @ 1 FPS) via WebSocket. FastAPI queues them into `LiveRequestQueue`.
- **Downstream**: `Runner.run_live()` yields events (audio, text, transcriptions, tool calls). FastAPI forwards them as JSON over WebSocket.
- **Tool execution**: ADK automatically handles `log_appliance` tool calls. The tool writes to `session.state["appliance_inventory"]`.

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI server with WebSocket endpoint `/ws/{user_id}/{session_id}` |
| `app/home_agent/agent.py` | ADK Agent definition (model, instruction, tools) |
| `app/home_agent/tools.py` | `log_appliance` tool — writes to session state |
| `app/home_agent/__init__.py` | Package init — exports `agent` |
| `app/static/index.html` | Web UI — chat, camera, transcription, console |
| `app/static/js/app.js` | Core JS — WebSocket, audio, camera, event handling |
| `app/static/js/audio-player.js` | Audio playback worklet setup (24kHz) |
| `app/static/js/audio-recorder.js` | Microphone capture worklet setup (16kHz) |
| `app/static/js/pcm-player-processor.js` | AudioWorkletProcessor — ring buffer playback |
| `app/static/js/pcm-recorder-processor.js` | AudioWorkletProcessor — mic frame capture |
| `app/static/css/style.css` | Stylesheet — split-pane layout, dark console |

## Build and Run Commands

```bash
# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Run server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run single test file
uv run pytest tests/test_tools.py -v
```

## ADK Patterns Used

- **Agent**: `google.adk.agents.Agent` with model, instruction, and tools
- **Tool with ToolContext**: `log_appliance` uses `tool_context.state` to read/write session state
- **LiveRequestQueue**: Queues upstream messages (audio blobs, text content, image blobs) for the Live API
- **Runner.run_live()**: Async generator yielding events from the bidi-streaming session
- **RunConfig**: `StreamingMode.BIDI`, `AudioTranscriptionConfig()` for input/output, `SessionResumptionConfig()`
- **Model**: `gemini-live-2.5-flash-native-audio` (configurable via `HOME_AGENT_MODEL` env var)

## Environment Variables

Set in `app/.env`:
- `GOOGLE_CLOUD_PROJECT` — GCP project ID
- `GOOGLE_CLOUD_LOCATION` — Region (default: `us-central1`)
- `GOOGLE_GENAI_USE_VERTEXAI` — Must be `TRUE` for Vertex AI
- `HOME_AGENT_MODEL` — Optional model override (default: `gemini-live-2.5-flash-native-audio`)

## Testing Conventions

- Framework: pytest with pytest-asyncio
- Config: `asyncio_mode = "auto"` in pyproject.toml
- Tool tests: Use `unittest.mock.MagicMock` for `ToolContext`
- Server tests: Use `fastapi.testclient.TestClient`
- Test files: `tests/test_tools.py`, `tests/test_agent.py`, `tests/test_main.py`

## Session State

The agent stores appliance inventory in `session.state["appliance_inventory"]` as a list of dicts:
```python
[
    {
        "appliance_type": "refrigerator",
        "make": "Samsung",
        "model": "RF28R7351SR",
        "location": "kitchen",
        "notes": ""
    }
]
```
