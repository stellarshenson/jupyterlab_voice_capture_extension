/**
 * AudioWorklet processor that downmixes to mono and converts Float32 to s16le frames.
 *
 * Capture/encoding runs off the UI thread (the worklet's audio rendering thread), so the
 * main thread stays free (D4). The AudioContext is created at 16 kHz, so the browser has
 * already resampled (B1); this processor only downmixes channels to mono and emits fixed
 * 320-sample (20 ms) s16le frames as binary ArrayBuffers (B2, B3, B4).
 *
 * The source is shipped as a string and loaded via a Blob URL so the labextension does not
 * have to serve an extra static asset.
 */

export const WORKLET_PROCESSOR_NAME = 'voice-capture-processor';

const WORKLET_SOURCE = `
class VoiceCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._frameSamples = 320;
    this._buf = new Float32Array(this._frameSamples);
    this._filled = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || !input[0]) {
      return true;
    }
    const channels = input.length;
    const n = input[0].length;
    for (let i = 0; i < n; i++) {
      let sample = 0;
      for (let c = 0; c < channels; c++) {
        sample += input[c][i];
      }
      sample /= channels; // downmix to mono

      this._buf[this._filled++] = sample;
      if (this._filled === this._frameSamples) {
        const pcm = new ArrayBuffer(this._frameSamples * 2);
        const view = new DataView(pcm);
        for (let j = 0; j < this._frameSamples; j++) {
          let s = this._buf[j];
          if (s > 1) { s = 1; } else if (s < -1) { s = -1; }
          const v = s < 0 ? s * 0x8000 : s * 0x7fff;
          view.setInt16(j * 2, Math.round(v), true);
        }
        this.port.postMessage(pcm, [pcm]);
        this._filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('${WORKLET_PROCESSOR_NAME}', VoiceCaptureProcessor);
`;

/**
 * Create an object URL for the worklet module. Callers should revoke it once the module
 * has been added (the browser caches the registered processor by name).
 */
export function workletModuleUrl(): string {
  const blob = new Blob([WORKLET_SOURCE], { type: 'application/javascript' });
  return URL.createObjectURL(blob);
}
