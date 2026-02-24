/**
 * AudioWorkletProcessor for PCM audio playback.
 * Implements a ring buffer to smooth out audio delivery from the WebSocket stream.
 * Input: Int16 PCM samples at 24kHz from the agent's audio output.
 * Output: Float32 samples to the AudioContext destination (speakers).
 */
class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Ring buffer: 24000 samples/sec * 180 sec = 4,320,000 samples max
    this.bufferSize = 24000 * 180;
    this.buffer = new Float32Array(this.bufferSize);
    this.writeIndex = 0;
    this.readIndex = 0;

    this.port.onmessage = (event) => {
      if (event.data === "endOfAudio") {
        this.buffer.fill(0);
        this.writeIndex = 0;
        this.readIndex = 0;
        return;
      }
      this._enqueue(event.data);
    };
  }

  _enqueue(int16Array) {
    for (let i = 0; i < int16Array.length; i++) {
      this.buffer[this.writeIndex] = int16Array[i] / 0x7fff;
      this.writeIndex = (this.writeIndex + 1) % this.bufferSize;
      if (this.writeIndex === this.readIndex) {
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      }
    }
  }

  process(inputs, outputs, parameters) {
    const output = outputs[0];
    const channel0 = output[0];
    const channel1 = output.length > 1 ? output[1] : null;

    for (let i = 0; i < channel0.length; i++) {
      if (this.readIndex !== this.writeIndex) {
        const sample = this.buffer[this.readIndex];
        channel0[i] = sample;
        if (channel1) channel1[i] = sample;
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      } else {
        channel0[i] = 0;
        if (channel1) channel1[i] = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-player-processor", PCMPlayerProcessor);
