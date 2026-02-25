/**
 * Audio playback using createBufferSource for gapless scheduling.
 * Replaces the worklet ring buffer approach for more reliable playback.
 */

// Module state for gapless scheduling and interrupt support
let nextStartTime = 0;
let scheduledSources = [];

/**
 * Plays a chunk of Int16 PCM audio at 24kHz through the given AudioContext.
 * Chunks are scheduled gaplessly back-to-back.
 * @param {AudioContext} audioContext - Shared AudioContext
 * @param {ArrayBuffer} arrayBuffer - Raw Int16 PCM data
 */
export function playAudioChunk(audioContext, arrayBuffer) {
  const pcmData = new Int16Array(arrayBuffer);
  const float32 = new Float32Array(pcmData.length);
  for (let i = 0; i < pcmData.length; i++) {
    float32[i] = pcmData[i] / 32768.0;
  }

  // Create buffer at 24kHz (Gemini output rate) — browser auto-resamples to context rate
  const buffer = audioContext.createBuffer(1, float32.length, 24000);
  buffer.getChannelData(0).set(float32);

  const source = audioContext.createBufferSource();
  source.buffer = buffer;
  source.connect(audioContext.destination);

  // Schedule gaplessly after previous chunk
  const now = audioContext.currentTime;
  nextStartTime = Math.max(now, nextStartTime);
  source.start(nextStartTime);
  nextStartTime += buffer.duration;

  // Track for interrupt cleanup
  scheduledSources.push(source);
  source.onended = () => {
    const idx = scheduledSources.indexOf(source);
    if (idx > -1) scheduledSources.splice(idx, 1);
  };
}

/**
 * Stops all scheduled audio sources immediately (for interrupts).
 * @param {AudioContext} audioContext - Shared AudioContext
 */
export function stopAudioPlayback(audioContext) {
  scheduledSources.forEach((s) => {
    try {
      s.stop();
    } catch {}
  });
  scheduledSources = [];
  if (audioContext) nextStartTime = audioContext.currentTime;
}
