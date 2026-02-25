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
- **Response modality**: Auto-detected from model name — `native-audio` models use `AUDIO` response modality, others use `TEXT`.

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI server with WebSocket endpoint `/ws/{user_id}/{session_id}`. Uses `sys.path.insert` to add `app/` dir so `home_agent` imports as top-level package (matches bidi-demo pattern). |
| `app/home_agent/agent.py` | ADK Agent definition — name: `home_appliance_detector`, model from `HOME_AGENT_MODEL` env var |
| `app/home_agent/tools.py` | `log_appliance(appliance_type, make, model, location, finish, tool_context, notes="", user_id="default_user")` — writes to session state |
| `app/home_agent/__init__.py` | Package init — `from .agent import agent` |
| `app/__init__.py` | Empty — makes `app` a Python package for test imports |
| `app/static/index.html` | Web UI — 3-section flow (auth → app → session-end), video+controls left, chat right, live transcription overlay, debug panels |
| `app/static/js/app.js` | Core JS — WebSocket connection, camera/screen at 1 FPS, mic toggle, live transcription overlay, chat from output transcriptions, inventory counter |
| `app/static/js/audio-player.js` | `playAudioChunk(audioContext, arrayBuffer)` — gapless `createBufferSource` scheduling at 24kHz, `stopAudioPlayback()` for interrupts |
| `app/static/js/audio-recorder.js` | `startAudioRecorderWorklet(audioContext, handler)` — shared AudioContext, downsamples native→16kHz, zero-gain feedback mute |
| `app/static/js/pcm-recorder-processor.js` | `PCMProcessor` — captures mic frames, posts Float32 via `port.postMessage` |
| `app/static/css/style.css` | Split-pane layout, Material Design-inspired, dark console, responsive at 768px |
| `tests/conftest.py` | Shared `app` fixture for test modules |
| `tests/test_tools.py` | 5 unit tests for `log_appliance` tool behavior |
| `tests/test_agent.py` | 7 tests for agent configuration (name, model, tools, instruction content) |
| `tests/test_main.py` | 6 tests — app init (3), WebSocket endpoint (1), message formats (2) |

## Build and Run Commands

```bash
# Install dependencies
uv sync --all-extras

# Run all tests (18 total)
uv run pytest tests/ -v

# Run server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run single test file
uv run pytest tests/test_tools.py -v

# Run with reduced log verbosity
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
```

## Dependency Versions (resolved)

- `google-adk==1.25.1` (spec: `>=1.20.0`)
- `fastapi==0.133.0` (spec: `>=0.115.0`)
- `uvicorn[standard]` (spec: `>=0.32.0`)
- `google-genai-sdk==1.64.0` (transitive via google-adk)
- Python 3.12 (spec: `>=3.10`)

## ADK Patterns Used

- **Agent**: `google.adk.agents.Agent` with model, instruction, and tools
- **Tool with ToolContext**: `log_appliance` uses `tool_context.state` to read/write session state. The `tool_context` param is auto-injected by ADK — not passed by the model.
- **LiveRequestQueue**: Queues upstream messages via `send_realtime(blob)` for audio/images and `send_content(content)` for text. Closed with `.close()` in `finally` block.
- **Runner.run_live()**: Async generator yielding `Event` objects. Events serialized via `model_dump_json(exclude_none=True, by_alias=True)`.
- **RunConfig**: `StreamingMode.BIDI`, `AudioTranscriptionConfig()` for input/output, `SessionResumptionConfig(handle=...)` for reconnection, `ProactivityConfig(proactive_audio=True)` for unprompted agent observations.
- **Model**: `gemini-live-2.5-flash-native-audio` — connects to Vertex AI via `v1beta1` API. The Live API WebSocket endpoint is `us-central1-aiplatform.googleapis.com`.

## Environment Variables

Set in `app/.env` (git-ignored, copied from `.env.template`):
- `GOOGLE_CLOUD_PROJECT` — GCP project ID (currently: `hybrid-vertex`)
- `GOOGLE_CLOUD_LOCATION` — Region (default: `us-central1`)
- `GOOGLE_GENAI_USE_VERTEXAI` — Must be `TRUE` for Vertex AI
- `HOME_AGENT_MODEL` — Optional model override (default: `gemini-live-2.5-flash-native-audio`)

Authentication: Uses Application Default Credentials (`gcloud auth application-default login`).

## Testing Conventions

- Framework: pytest with pytest-asyncio (`asyncio_mode = "auto"`)
- 18 total tests across 3 files
- Tool tests (`test_tools.py`): Use `unittest.mock.MagicMock` for `ToolContext` with `mock_context.state = {}` dict
- Agent tests (`test_agent.py`): Import agent, verify config properties (no mocking needed)
- Server tests (`test_main.py`): Use `fastapi.testclient.TestClient`. WebSocket tests use unique session IDs to avoid `AlreadyExistsError` from `InMemorySessionService` singleton.
- No Live API credentials required for tests — tests verify structure and message acceptance, not end-to-end API calls.

## Session State

The agent stores appliance inventory in `session.state["appliance_inventory"]` as a list of dicts:
```python
[
    {
        "appliance_type": "refrigerator",
        "make": "Samsung",
        "model": "RF28R7351SR",
        "location": "kitchen",
        "finish": "stainless steel",
        "notes": "",
        "user_id": "default_user"
    }
]
```

## Known Behaviors

- **Browser disconnect**: When a browser tab closes, the upstream task logs `Cannot call "receive" once a disconnect message has been received.` — this is expected, not a bug.
- **Keepalive pings**: The Vertex AI Live API WebSocket sends keepalive pings every 20 seconds. These are handled automatically by the websockets library.
- **Pydantic warnings**: Suppressed via `warnings.filterwarnings` — caused by `response_modalities` enum serialization.
- **Session duration**: Vertex AI Live API has a 10-minute session limit (both audio-only and with video). Session resumption is configured but reconnection UI is not yet implemented.

## Project Structure

```
bidi-adk-live/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI + WebSocket server
│   ├── .env                     # Vertex AI config (git-ignored)
│   ├── home_agent/
│   │   ├── __init__.py          # from .agent import agent
│   │   ├── agent.py             # ADK Agent definition
│   │   └── tools.py             # log_appliance tool
│   └── static/
│       ├── index.html
│       ├── css/style.css
│       └── js/
│           ├── app.js
│           ├── audio-player.js
│           ├── audio-recorder.js
│           └── pcm-recorder-processor.js
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_tools.py            # 5 tests
│   ├── test_agent.py            # 7 tests
│   └── test_main.py             # 6 tests
├── docs/plans/
│   └── 2026-02-24-home-appliance-detector.md
├── pyproject.toml
├── .env.template
├── .gitignore
├── CLAUDE.md
└── README.md
```
