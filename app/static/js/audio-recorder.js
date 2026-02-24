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
