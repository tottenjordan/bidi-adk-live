/**
 * Microphone capture using a shared AudioContext.
 * Downsamples from native sample rate to 16kHz for the Gemini Live API.
 * Uses a zero-gain node to prevent mic audio feedback to speakers.
 *
 * @param {AudioContext} audioContext - Shared AudioContext (browser default rate)
 * @param {Function} audioRecorderHandler - Called with Int16Array PCM chunks at 16kHz
 * @returns {Promise<[AudioWorkletNode, MediaStream]>} - Node and stream for cleanup
 */
let workletRegistered = false;

export async function startAudioRecorderWorklet(audioContext, audioRecorderHandler) {
  // Ensure context is running (may be suspended if user gesture was earlier)
  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }

  // Only register the worklet module once per AudioContext
  if (!workletRegistered) {
    const workletURL = new URL("./pcm-recorder-processor.js", import.meta.url);
    await audioContext.audioWorklet.addModule(workletURL);
    workletRegistered = true;
  }

  const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const source = audioContext.createMediaStreamSource(micStream);
  const recorderNode = new AudioWorkletNode(audioContext, "pcm-recorder-processor");

  recorderNode.port.onmessage = (event) => {
    const float32Data = event.data;
    const downsampled = downsampleBuffer(float32Data, audioContext.sampleRate, 16000);
    const int16Data = convertFloat32ToPCM(downsampled);
    audioRecorderHandler(int16Data);
  };

  source.connect(recorderNode);

  // Mute local feedback — connect through zero-gain node
  const muteGain = audioContext.createGain();
  muteGain.gain.value = 0;
  recorderNode.connect(muteGain);
  muteGain.connect(audioContext.destination);

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
 * Resets worklet registration state. Call when creating a new AudioContext.
 */
export function resetRecorderState() {
  workletRegistered = false;
}

/**
 * Downsamples a Float32Array buffer from one sample rate to another.
 * Uses simple averaging for anti-aliasing.
 */
function downsampleBuffer(buffer, fromRate, toRate) {
  if (fromRate === toRate) return buffer;
  const ratio = fromRate / toRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  for (let i = 0; i < newLength; i++) {
    const start = Math.round(i * ratio);
    const end = Math.round((i + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (let j = start; j < end && j < buffer.length; j++) {
      sum += buffer[j];
      count++;
    }
    result[i] = sum / count;
  }
  return result;
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
