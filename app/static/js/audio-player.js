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
