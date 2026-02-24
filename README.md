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
