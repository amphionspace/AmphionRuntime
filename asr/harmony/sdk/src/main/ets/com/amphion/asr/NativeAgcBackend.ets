import { closeAgc, createAgc, processAgc, AgcHandle } from 'libamphion_asr.so';
import { AgcBackend } from './StreamingAgcProcessor';

/** Per-session owner of the native WebRTC AGC2 processor. */
export class NativeAgcBackend implements AgcBackend {
  private handle?: AgcHandle;

  constructor(sampleRate: number) {
    this.handle = createAgc(sampleRate);
  }

  process(frame: Float32Array): Float32Array {
    if (this.handle === undefined) throw new Error('AGC backend is closed');
    const output = frame.slice();
    return processAgc(this.handle, output);
  }

  close(): void {
    if (this.handle === undefined) return;
    closeAgc(this.handle);
    this.handle = undefined;
  }
}
