export type FrameListener = (frame: ArrayBuffer) => void;

const FRAME_SAMPLES = 320; // 640 bytes = 20 ms @ 16 kHz mono S16LE (DINGQIAO_AUDIO_FRAME_BYTES)

/**
 * Re-frames arbitrary-length PCM into fixed 640-byte frames required by the Dingqiao SDK. Mirrors the
 * Android PcmFrameWriter so no tail samples are dropped between AudioCapturer callbacks.
 */
export class PcmFrameWriter {
  private readonly onFrame: FrameListener;
  private pending: Int16Array = new Int16Array(0);

  constructor(onFrame: FrameListener) {
    this.onFrame = onFrame;
  }

  accept(samples: Int16Array): void {
    if (samples.length === 0) return;
    if (this.pending.length === 0) {
      this.pending = samples.slice(0);
    } else {
      const merged = new Int16Array(this.pending.length + samples.length);
      merged.set(this.pending, 0);
      merged.set(samples, this.pending.length);
      this.pending = merged;
    }
    let offset = 0;
    while (this.pending.length - offset >= FRAME_SAMPLES) {
      // Build into an explicit ArrayBuffer; Int16Array.buffer is ArrayBufferLike, which ArkTS will
      // not structurally narrow to the ArrayBuffer the SDK's writeAudio expects.
      const out = new ArrayBuffer(FRAME_SAMPLES * 2);
      new Int16Array(out).set(this.pending.subarray(offset, offset + FRAME_SAMPLES), 0);
      this.onFrame(out);
      offset += FRAME_SAMPLES;
    }
    this.pending = offset > 0 ? this.pending.slice(offset) : this.pending;
  }

  reset(): void {
    this.pending = new Int16Array(0);
  }

  flushFinalFrame(): void {
    if (this.pending.length === 0) return;
    const out = new ArrayBuffer(FRAME_SAMPLES * 2);
    new Int16Array(out).set(this.pending, 0);
    this.pending = new Int16Array(0);
    this.onFrame(out);
  }
}
