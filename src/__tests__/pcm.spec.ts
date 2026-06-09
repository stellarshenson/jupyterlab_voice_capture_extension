import { floatToS16LE, Framer, FRAME_BYTES, FRAME_SAMPLES } from '../pcm';

describe('floatToS16LE', () => {
  it('maps full scale to the int16 range, little-endian (B2)', () => {
    const buf = floatToS16LE(Float32Array.from([1, -1, 0, 0.5]));
    const view = new DataView(buf);
    expect(buf.byteLength).toBe(8);
    expect(view.getInt16(0, true)).toBe(32767); // +1.0 -> 0x7FFF
    expect(view.getInt16(2, true)).toBe(-32768); // -1.0 -> -0x8000
    expect(view.getInt16(4, true)).toBe(0);
    expect(view.getInt16(6, true)).toBe(Math.round(0.5 * 0x7fff));
    // little-endian byte order for +1.0 (0x7FFF): low byte first
    const bytes = new Uint8Array(buf);
    expect(bytes[0]).toBe(0xff);
    expect(bytes[1]).toBe(0x7f);
  });

  it('clamps out-of-range samples', () => {
    const view = new DataView(floatToS16LE(Float32Array.from([2, -2])));
    expect(view.getInt16(0, true)).toBe(32767);
    expect(view.getInt16(2, true)).toBe(-32768);
  });
});

describe('Framer', () => {
  it('emits a fixed-size frame only once full (B3)', () => {
    const framer = new Framer();
    expect(framer.push(new Float32Array(FRAME_SAMPLES - 1))).toHaveLength(0);
    const frames = framer.push(new Float32Array(1));
    expect(frames).toHaveLength(1);
    expect(frames[0].byteLength).toBe(FRAME_BYTES);
  });

  it('splits a long chunk into whole frames and keeps the remainder', () => {
    const framer = new Framer();
    const frames = framer.push(new Float32Array(FRAME_SAMPLES * 2 + 5));
    expect(frames).toHaveLength(2);
    frames.forEach(f => expect(f.byteLength).toBe(FRAME_BYTES));
    // the 5 leftover samples are buffered; one more near-frame completes it
    expect(framer.push(new Float32Array(FRAME_SAMPLES - 5))).toHaveLength(1);
  });
});
