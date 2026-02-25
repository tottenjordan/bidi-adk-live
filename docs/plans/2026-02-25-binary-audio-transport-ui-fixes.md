# Binary Audio Transport & Conversation Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `executing-plans` skill to implement this plan task-by-task.

**Goal:** Fix conversational audio errors by switching downstream audio from base64-in-JSON to raw binary WebSocket frames, accumulating upstream PCM buffers, and fixing transcription state bugs.

**Architecture:** The backend will extract audio `inline_data` from ADK events and send it as binary WebSocket frames (`send_bytes`), while forwarding the remaining event metadata as JSON text frames (`send_text`). The frontend will discriminate binary vs text messages at the WebSocket level — binary goes directly to the audio scheduler, text gets JSON-parsed for transcriptions/events. This eliminates base64 encoding overhead (~33% bandwidth savings) and removes per-chunk `atob()` + array conversion on the main thread.

**Tech Stack:** FastAPI WebSocket (binary + text frames), ADK `Runner.run_live()`, Web Audio API (`AudioWorklet`, `createBufferSource`), vanilla JS (ES modules).

**Reference implementation:** [`plain-js-python-sdk-demo-app`](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api/native-audio-websocket-demo-apps/plain-js-python-sdk-demo-app) — uses raw GenAI SDK, but the audio transport and media handling patterns apply directly.

---

## Analysis: Root Causes of Conversational Errors

Before implementing, here's what the reference app does differently that likely explains our audio issues:

| Issue | Our App (Current) | Reference App | Impact |
|-------|-------------------|---------------|--------|
| **Downstream audio encoding** | Base64 inside JSON event (~33% overhead) | Raw binary WebSocket frames | High latency, bandwidth waste |
| **Audio decode per chunk** | `atob()` + byte-by-byte `charCodeAt` loop | Direct `Int16Array(arrayBuffer)` view | CPU overhead on every chunk |
| **Upstream buffer size** | 128 samples per message (~2.7ms at 48kHz) | 4096 samples per message (~85ms at 48kHz) | ~30x more WebSocket messages/sec |
| **Transcription state on turn_complete** | `accumulatedOutputTranscription` NOT reset | Message pointers nulled on turn_complete | Stale text leaks into next turn |
| **Transcription state on interrupted** | `accumulatedOutputTranscription` NOT reset | Message pointers nulled on interrupted | Stale text after interrupt |
| **Input transcription in chat** | Only shown in debug panel | Shown as user messages in chat | User can't see what was heard |

---

## Task 1: Backend — Send Audio as Binary WebSocket Frames

**Files:**
- Modify: `app/main.py:145-161` (downstream_task)
- Test: `tests/test_main.py`

This is the highest-impact change. Currently, `downstream_task` serializes the entire ADK event (including audio) as JSON and sends it as a text frame. After this change, audio data will be extracted and sent as binary frames, while the remaining event metadata goes as JSON text.

**Step 1: Write the failing test**

Add a test to `tests/test_main.py` that verifies audio data arrives as binary WebSocket frames:

```python
def test_downstream_audio_sent_as_binary(self):
    """Audio inline_data should be sent as binary WebSocket frames, not base64 JSON."""
    # This test validates the transport format, not the actual audio content.
    # We verify that the server sends binary frames when events contain audio.
    pass  # Placeholder — actual test requires mocking runner.run_live
```

Since `downstream_task` depends on `runner.run_live()` which requires a live Gemini session, and our existing tests don't mock the runner, skip writing a unit test for this. Instead, validate manually by checking the debug console after implementation.

**Step 2: Modify `downstream_task` in `app/main.py`**

Replace the current downstream_task (lines 145-161) with logic that:
1. Inspects each event for `content.parts` containing `inline_data` with audio mime types
2. Extracts the raw audio bytes and sends them via `websocket.send_bytes()`
3. Strips the audio parts from the event before sending the remaining JSON via `websocket.send_text()`

```python
async def downstream_task():
    """Stream agent events back to the client.

    Audio data is sent as binary WebSocket frames for low-latency playback.
    All other event data (transcriptions, turn_complete, etc.) is sent as JSON text.
    """
    try:
        async for event in runner.run_live(
            session_id=session_id,
            user_id=user_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
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
                event.content.parts = non_audio_parts if non_audio_parts else None

                # If no content remains after stripping audio, clear it
                if not event.content.parts:
                    event.content = None

            # Send remaining event metadata as JSON text
            # (transcriptions, turn_complete, interrupted, function_response, etc.)
            # Only send if there's meaningful data beyond empty content
            event_json = event.model_dump_json(
                exclude_none=True, by_alias=True
            )
            # Always send the event JSON — even if content was stripped,
            # there may be turn_complete, interrupted, transcription fields
            if event_json != "{}":
                await websocket.send_text(event_json)
    except WebSocketDisconnect:
        logger.info("Client disconnected (downstream): user=%s", user_id)
    except Exception as e:
        logger.exception("Downstream error: %s", e)
```

**Step 3: Run existing tests to verify no regressions**

```bash
uv run pytest tests/ -v
```

Expected: All 18 tests pass. The existing tests don't exercise the downstream audio path (no live Gemini session), so they should pass unchanged.

**Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: send audio as binary WebSocket frames instead of base64 JSON"
```

---

## Task 2: Frontend — Handle Binary WebSocket Messages for Audio

**Files:**
- Modify: `app/static/js/app.js:78-80` (ws.onmessage handler)
- Modify: `app/static/js/app.js:257-265` (playAudio function)

After Task 1, the server sends audio as binary frames and events as JSON text. The frontend must discriminate between the two at the WebSocket level.

**Step 1: Update `ws.onmessage` to handle binary audio**

Replace the current handler (lines 78-80):

```javascript
// BEFORE:
ws.onmessage = (event) => {
    handleServerEvent(event.data);
};

// AFTER:
ws.onmessage = (event) => {
    if (typeof event.data === "string") {
        // JSON text frame — event metadata (transcriptions, turn_complete, etc.)
        handleServerEvent(event.data);
    } else {
        // Binary frame — raw PCM audio from Gemini
        playAudioChunk(audioContext, event.data);
    }
};
```

**Step 2: Remove the `playAudio` base64 decode function**

Delete the `playAudio()` function (lines 257-265) since audio no longer arrives as base64:

```javascript
// DELETE THIS ENTIRE FUNCTION:
function playAudio(base64Data) {
    if (!audioContext) return;
    const binaryStr = atob(base64Data);
    const bytes = new Uint8Array(binaryStr.length);
    for (let i = 0; i < binaryStr.length; i++) {
        bytes[i] = binaryStr.charCodeAt(i);
    }
    playAudioChunk(audioContext, bytes.buffer);
}
```

**Step 3: Remove audio extraction from `handleServerEvent`**

In the `handleServerEvent` function (lines 168-177), remove the audio part processing since audio now arrives as binary frames. Keep the text part processing:

```javascript
// BEFORE (lines 168-177):
if (event.content?.parts) {
    for (const part of event.content.parts) {
        if (part.inline_data?.mime_type?.startsWith("audio/")) {
            playAudio(part.inline_data.data);
        }
        if (part.text) {
            updateAgentMessage(part.text, event.partial === true);
        }
    }
}

// AFTER:
if (event.content?.parts) {
    for (const part of event.content.parts) {
        if (part.text) {
            updateAgentMessage(part.text, event.partial === true);
        }
    }
}
```

**Step 4: Remove `hasAudioData` function**

Delete the `hasAudioData()` function (lines 218-223) — no longer needed since audio events don't arrive as JSON:

```javascript
// DELETE:
function hasAudioData(event) { ... }
```

Update the console logging (lines 162-166) to remove the audio filter since audio events no longer appear in the JSON stream:

```javascript
// BEFORE:
const isAudioEvent = hasAudioData(event);
if (!isAudioEvent || !filterAudioCheckbox.checked) {
    logConsole(event.author || "system", JSON.stringify(event, null, 2), isAudioEvent);
}

// AFTER:
logConsole(event.author || "system", JSON.stringify(event, null, 2));
```

**Step 5: Commit**

```bash
git add app/static/js/app.js
git commit -m "feat: handle binary audio WebSocket frames, remove base64 decode path"
```

---

## Task 3: Frontend — Accumulate PCM Recorder Buffer (Reduce Message Frequency)

**Files:**
- Modify: `app/static/js/pcm-recorder-processor.js`

Our worklet sends every 128-sample frame (~370 messages/sec at 48kHz). The reference accumulates 4096 samples (~12 messages/sec). This reduces WebSocket overhead dramatically.

**Step 1: Add buffer accumulation to the PCM recorder worklet**

Replace the entire file:

```javascript
/**
 * AudioWorkletProcessor for microphone PCM capture.
 * Accumulates samples into a 4096-sample buffer before sending
 * to reduce WebSocket message frequency.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 4096;
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input.length) return true;

    const channelData = input[0];

    for (let i = 0; i < channelData.length; i++) {
      this.buffer[this.bufferIndex++] = channelData[i];

      if (this.bufferIndex >= this.bufferSize) {
        this.port.postMessage(this.buffer.slice());
        this.bufferIndex = 0;
      }
    }

    return true;
  }
}

registerProcessor("pcm-recorder-processor", PCMProcessor);
```

Key differences from current:
- Accumulates 4096 Float32 samples before posting (was: posts every 128)
- Uses `this.buffer.slice()` to send a copy (prevents race with next fill)
- At 48kHz native rate: sends ~12 messages/sec instead of ~370/sec
- After downsampling to 16kHz: ~1365 samples per message (~85ms of audio)

**Step 2: Commit**

```bash
git add app/static/js/pcm-recorder-processor.js
git commit -m "perf: accumulate 4096 samples in PCM worklet to reduce message frequency"
```

---

## Task 4: Frontend — Fix Transcription State Bugs

**Files:**
- Modify: `app/static/js/app.js:148-151` (finalizeAgentMessage)
- Modify: `app/static/js/app.js:179-186` (turn_complete + interrupted handling)
- Modify: `app/static/js/app.js:188-207` (input transcription display)

These are the state bugs most likely to cause conversational glitches — stale accumulated text leaking across turns.

**Step 1: Reset `accumulatedOutputTranscription` on `turn_complete` and `interrupted`**

Update the `finalizeAgentMessage()` function (line 148-151):

```javascript
// BEFORE:
function finalizeAgentMessage() {
    currentAgentMessageEl = null;
    currentAgentText = "";
}

// AFTER:
function finalizeAgentMessage() {
    currentAgentMessageEl = null;
    currentAgentText = "";
    accumulatedOutputTranscription = "";
}
```

**Step 2: Show input transcriptions as user messages in chat**

When input transcription is finished, show it as a user message in the chat (not just the debug panel). This matches the reference app's behavior and lets the user see what the model heard.

Update the input transcription handler (lines 188-189):

```javascript
// BEFORE:
if (event.input_transcription?.text) {
    updateTranscription("user", event.input_transcription.text, event.input_transcription.finished);
}

// AFTER:
if (event.input_transcription?.text) {
    updateTranscription("user", event.input_transcription.text, event.input_transcription.finished);
    // Show finished user transcription in chat so user sees what the model heard
    if (event.input_transcription.finished) {
        addMessage("user", event.input_transcription.text);
    }
}
```

**Step 3: Commit**

```bash
git add app/static/js/app.js
git commit -m "fix: reset transcription state on turn boundaries, show input in chat"
```

---

## Task 5: Frontend — Clean Up Console Logging and Audio Filter UI

**Files:**
- Modify: `app/static/index.html:79-82` (remove audio filter checkbox)
- Modify: `app/static/js/app.js:464-496` (simplify logConsole)

Since audio events no longer appear in the JSON event stream (they're binary frames), the "Hide audio events" checkbox is unnecessary.

**Step 1: Remove the audio filter checkbox from HTML**

In `app/static/index.html`, replace lines 79-82:

```html
<!-- BEFORE: -->
<label class="filter-toggle">
    <input type="checkbox" id="filterAudio" checked />
    Hide audio events
</label>

<!-- AFTER: remove entirely -->
```

**Step 2: Simplify logConsole function**

Remove the `isAudio` parameter and audio-event CSS class logic from `logConsole()`:

```javascript
// BEFORE (line 464):
function logConsole(author, message, isAudio = false) {
    const entry = document.createElement("div");
    entry.className = `console-entry ${isAudio ? "audio-event" : ""}`;

// AFTER:
function logConsole(author, message) {
    const entry = document.createElement("div");
    entry.className = "console-entry";
```

**Step 3: Remove `filterAudioCheckbox` DOM reference**

Delete line 28:
```javascript
// DELETE:
const filterAudioCheckbox = document.getElementById("filterAudio");
```

**Step 4: Commit**

```bash
git add app/static/index.html app/static/js/app.js
git commit -m "chore: remove audio event filter (audio no longer in JSON stream)"
```

---

## Task 6: Run Full Test Suite and Manual Validation

**Step 1: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All 18 tests pass.

**Step 2: Manual validation checklist**

Start the server and test in the browser:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify each item:

- [ ] **Connect**: Click "Connect" button, verify status pill turns green
- [ ] **Agent greeting**: Agent should greet within a few seconds (audio plays)
- [ ] **Mic toggle**: Click "Mic" button, speak, verify input transcription appears in chat
- [ ] **Audio playback**: Agent audio plays smoothly without gaps
- [ ] **Interruption**: Speak while agent is talking, verify agent audio stops
- [ ] **Camera toggle**: Click "Camera", verify video appears and agent reacts to visual input
- [ ] **Screen share**: Click "Screen", verify screen capture works
- [ ] **Text input**: Type a message, verify agent responds
- [ ] **Disconnect**: Click "Disconnect", verify session-end screen appears
- [ ] **Restart**: Click "Start New Session", verify clean restart
- [ ] **Turn boundaries**: After agent finishes speaking, verify next response starts fresh (no stale text)
- [ ] **Debug panel**: Toggle debug panel, verify transcriptions and events logged correctly
- [ ] **Console log format**: Verify no audio events in event console (they're binary now)

**Step 3: Final commit**

```bash
git add -A
git commit -m "test: verify full test suite passes after binary audio transport changes"
```

---

## Summary of Changes

| File | Change | Why |
|------|--------|-----|
| `app/main.py` | Extract audio from ADK events, send as `send_bytes()` | Eliminate base64 overhead, reduce latency |
| `app/static/js/app.js` | Handle binary WebSocket messages, remove base64 decode | Match binary transport |
| `app/static/js/app.js` | Reset `accumulatedOutputTranscription` on turn boundaries | Fix stale text across turns |
| `app/static/js/app.js` | Show input transcription in chat | User sees what model heard |
| `app/static/js/app.js` | Remove audio filter logic | Audio events no longer in JSON |
| `app/static/js/pcm-recorder-processor.js` | Accumulate 4096 samples before posting | Reduce upstream message frequency 30x |
| `app/static/index.html` | Remove audio filter checkbox | No longer applicable |

## What We're NOT Changing (and Why)

- **Not replacing ADK with raw GenAI SDK**: The reference app uses `genai.Client.aio.live.connect()` directly, bypassing ADK. We keep ADK because it provides agent/tool infrastructure (`log_appliance` tool, session state management). The binary audio extraction in Task 1 gives us the same transport efficiency.
- **Not adding a `GeminiClient` class**: The reference wraps WebSocket in a class. Our inline WebSocket code in `app.js` is already clean and well-structured for a single-page app. Adding a class would be refactoring without functional benefit.
- **Not adding a `MediaHandler` class**: Same reasoning. Our `audio-player.js` and `audio-recorder.js` modules already provide clean separation. The reference merges everything into one class because it uses vanilla script tags instead of ES modules.
- **Not changing the UI layout**: Our current layout (video left, chat right, debug below) already matches the reference app's grid layout closely.
