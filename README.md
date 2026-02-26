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
5. The agent will ask for brand, model number, finish, location, and notes
6. After saving, the agent confirms and mentions the total count

## Testing

### Unit and Integration Tests

```bash
uv run pytest tests/ -v
```

This runs 25 tests covering tool logic (session-state and BigQuery), agent configuration, and WebSocket message handling. No Vertex AI credentials are required for these tests.

### Manual Server Testing

1. Start the server:
   ```bash
   uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. Open http://localhost:8000 in Chrome (requires WebRTC support for mic/camera).

3. Verify the connection status indicator in the top-right turns green ("Connected").

4. Click **Camera** — you should see your camera feed in the side panel and the event console should show WebSocket activity.

5. Click **Mic** — speak to the agent. The transcription panel should display your speech in real-time.

6. Point the camera at a home appliance — the agent should describe what it sees and ask if you want to log it. Confirm to test the `log_appliance_bq` tool call. The agent will ask for brand, model number, finish, location, and notes before saving. The inventory counter above the controls should increment.

7. Check the **Event Console** (bottom-right) for Live API events. Uncheck "Hide audio events" to see raw audio data events.

## Architecture

- **Backend**: FastAPI + WebSocket + Google ADK `Runner.run_live()`
- **Frontend**: Vanilla JS with Web Audio API worklets
- **Model**: `gemini-live-2.5-flash-native-audio` via Vertex AI Live API
- **Streaming**: Separate upstream/downstream async tasks for optimal performance
