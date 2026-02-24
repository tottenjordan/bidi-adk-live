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
let isScreenActive = false;
let cameraStream = null;
let screenStream = null;
let cameraInterval = null;
let screenInterval = null;
const CAMERA_FPS = 1;

// --- DOM Elements ---
const messagesEl = document.getElementById("messages");
const textForm = document.getElementById("textForm");
const textInput = document.getElementById("textInput");
const micBtn = document.getElementById("micBtn");
const cameraBtn = document.getElementById("cameraBtn");
const screenBtn = document.getElementById("screenBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const connectionStatus = document.getElementById("connectionStatus");
const consoleContent = document.getElementById("consoleContent");
const filterAudioCheckbox = document.getElementById("filterAudio");
const videoContainer = document.getElementById("videoContainer");
const cameraPreview = document.getElementById("cameraPreview");
const captureCanvas = document.getElementById("captureCanvas");
const videoPlaceholder = document.getElementById("videoPlaceholder");
const inventoryCount = document.getElementById("inventoryCount");
const transcriptionContent = document.getElementById("transcriptionContent");
const debugToggle = document.getElementById("debugToggle");
const debugPanels = document.getElementById("debugPanels");

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
    updateConnectionStatus("connected");
    logConsole("system", "Connected to server");
  };

  ws.onclose = () => {
    updateConnectionStatus("disconnected");
    logConsole("system", "Disconnected from server");
    setTimeout(connect, 5000);
  };

  ws.onerror = (error) => {
    updateConnectionStatus("error");
    logConsole("error", `WebSocket error: ${error.message || "Unknown error"}`);
  };

  ws.onmessage = (event) => {
    handleServerEvent(event.data);
  };
}

function updateConnectionStatus(state) {
  connectionStatus.className = `status ${state}`;
  const labels = {
    connected: "Connected",
    disconnected: "Disconnected",
    error: "Error",
  };
  connectionStatus.textContent = labels[state] || "Disconnected";
}

// --- Disconnect ---
function disconnect() {
  if (isMicActive) {
    stopMicrophone(micStream);
    micStream = null;
    isMicActive = false;
    micBtn.textContent = "Mic";
    micBtn.classList.remove("active");
  }
  if (isCameraActive) {
    stopCamera();
  }
  if (isScreenActive) {
    stopScreen();
  }
  if (ws) {
    ws.onclose = null; // prevent auto-reconnect
    ws.close();
    ws = null;
  }
  updateConnectionStatus("disconnected");
  logConsole("system", "Disconnected by user");
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
  currentAgentText = text;
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

  if (!isAudioEvent || !filterAudioCheckbox.checked) {
    logConsole(event.author || "system", JSON.stringify(event, null, 2), isAudioEvent);
  }

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

  if (event.turn_complete) {
    finalizeAgentMessage();
  }

  if (event.interrupted) {
    if (audioPlayerNode) {
      audioPlayerNode.port.postMessage("endOfAudio");
    }
    finalizeAgentMessage();
  }

  if (event.input_transcription?.text) {
    updateTranscription("user", event.input_transcription.text, event.input_transcription.finished);
  }
  if (event.output_transcription?.text) {
    updateTranscription("agent", event.output_transcription.text, event.output_transcription.finished);
    // Stream output transcriptions into the chat as agent messages in real-time.
    // For native audio models, this is the only text representation of the response.
    updateAgentMessage(event.output_transcription.text, !event.output_transcription.finished);
  }

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
    micBtn.textContent = "Mic";
    micBtn.classList.remove("active");
  } else {
    await initAudioPlayer();
    [audioRecorderNode, micStream] = await startAudioRecorderWorklet((pcmData) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(pcmData.buffer);
      }
    });
    isMicActive = true;
    micBtn.textContent = "Mic On";
    micBtn.classList.add("active");
  }
}

// --- Camera ---
async function toggleCamera() {
  if (isCameraActive) {
    stopCamera();
  } else {
    // Stop screen share if active (mutually exclusive)
    if (isScreenActive) {
      stopScreen();
    }
    await startCamera();
  }
}

async function startCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { width: 768, height: 768, facingMode: "environment" },
    });
    cameraPreview.srcObject = cameraStream;
    cameraPreview.classList.add("active");
    videoPlaceholder.style.display = "none";
    isCameraActive = true;
    cameraBtn.textContent = "Camera On";
    cameraBtn.classList.add("active");

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
  cameraPreview.classList.remove("active");
  if (!isScreenActive) {
    videoPlaceholder.style.display = "flex";
  }
  isCameraActive = false;
  cameraBtn.textContent = "Camera";
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

// --- Screen Share ---
async function toggleScreen() {
  if (isScreenActive) {
    stopScreen();
  } else {
    // Stop camera if active (mutually exclusive)
    if (isCameraActive) {
      stopCamera();
    }
    await startScreen();
  }
}

async function startScreen() {
  try {
    screenStream = await navigator.mediaDevices.getDisplayMedia({
      video: { width: 1280, height: 720 },
    });
    cameraPreview.srcObject = screenStream;
    cameraPreview.classList.add("active");
    videoPlaceholder.style.display = "none";
    isScreenActive = true;
    screenBtn.textContent = "Screen On";
    screenBtn.classList.add("active");

    // Stop sharing when the user clicks "Stop sharing" in the browser UI
    screenStream.getVideoTracks()[0].addEventListener("ended", () => {
      stopScreen();
    });

    screenInterval = setInterval(captureAndSendScreenFrame, 1000 / CAMERA_FPS);
  } catch (err) {
    logConsole("error", `Screen share error: ${err.message}`);
  }
}

function stopScreen() {
  if (screenInterval) {
    clearInterval(screenInterval);
    screenInterval = null;
  }
  if (screenStream) {
    screenStream.getTracks().forEach((track) => track.stop());
    screenStream = null;
  }
  cameraPreview.srcObject = null;
  cameraPreview.classList.remove("active");
  if (!isCameraActive) {
    videoPlaceholder.style.display = "flex";
  }
  isScreenActive = false;
  screenBtn.textContent = "Screen";
  screenBtn.classList.remove("active");
}

function captureAndSendScreenFrame() {
  if (!screenStream || !ws || ws.readyState !== WebSocket.OPEN) return;

  const video = cameraPreview;
  const canvas = captureCanvas;
  canvas.width = video.videoWidth || 1280;
  canvas.height = video.videoHeight || 720;

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

// --- Debug Panel Toggle ---
function toggleDebugPanel() {
  const isHidden = debugPanels.style.display === "none";
  debugPanels.style.display = isHidden ? "grid" : "none";
  debugToggle.textContent = isHidden ? "Hide Debug Panel" : "Show Debug Panel";
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
screenBtn.addEventListener("click", toggleScreen);
disconnectBtn.addEventListener("click", disconnect);
debugToggle.addEventListener("click", toggleDebugPanel);

// --- Initialize ---
connect();
