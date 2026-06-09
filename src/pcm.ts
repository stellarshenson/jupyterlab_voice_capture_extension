/**
 * Pure PCM helpers shared by the audio worklet and the unit tests.
 *
 * The wire contract (see docs/acc-crit-voice-capture.md): signed 16-bit little-endian,
 * 16 kHz, mono; one frame = 20 ms of audio = 320 samples = 640 bytes.
 */

export const TARGET_SAMPLE_RATE = 16000;
export const FRAME_SAMPLES = 320; // 20 ms at 16 kHz
export const FRAME_BYTES = FRAME_SAMPLES * 2; // s16le -> 2 bytes per sample

/**
 * Convert Float32 samples in [-1, 1] to signed 16-bit little-endian PCM.
 *
 * The int16 range is asymmetric: -1.0 maps to -32768 and +1.0 to +32767.
 */
export function floatToS16LE(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i++) {
    let s = samples[i];
    if (s > 1) {
      s = 1;
    } else if (s < -1) {
      s = -1;
    }
    const v = s < 0 ? s * 0x8000 : s * 0x7fff;
    view.setInt16(i * 2, Math.round(v), true);
  }
  return buffer;
}

/**
 * Accumulates Float32 samples and emits fixed-size s16le frames as they fill.
 *
 * Used by the Jest tests; the worklet re-implements the same math inline because it runs
 * in a separate module context that cannot import this file.
 */
export class Framer {
  private _buf = new Float32Array(FRAME_SAMPLES);
  private _filled = 0;

  push(chunk: Float32Array): ArrayBuffer[] {
    const frames: ArrayBuffer[] = [];
    let offset = 0;
    while (offset < chunk.length) {
      const take = Math.min(
        FRAME_SAMPLES - this._filled,
        chunk.length - offset
      );
      this._buf.set(chunk.subarray(offset, offset + take), this._filled);
      this._filled += take;
      offset += take;
      if (this._filled === FRAME_SAMPLES) {
        frames.push(floatToS16LE(this._buf));
        this._filled = 0;
      }
    }
    return frames;
  }
}
