export class SpeakerPcmBuffers {
  private maxSamples: number;
  private speakerVadParts: Float32Array[] = [];
  private fallbackParts: Float32Array[] = [];
  private speakerVadSampleCount: number = 0;
  private fallbackSampleCount: number = 0;

  constructor(maxSamples: number) {
    this.maxSamples = Math.max(1, Math.round(maxSamples));
  }

  observe(samples: Float32Array, captureSpeakerVad: boolean, captureFallback: boolean): void {
    if (captureSpeakerVad) {
      const retained = Math.min(samples.length, this.maxSamples - this.speakerVadSampleCount);
      if (retained > 0) {
        this.speakerVadParts.push(samples.slice(0, retained));
        this.speakerVadSampleCount += retained;
      }
    }
    if (captureFallback) {
      const retained = Math.min(samples.length, this.maxSamples - this.fallbackSampleCount);
      if (retained > 0) {
        this.fallbackParts.push(samples.slice(0, retained));
        this.fallbackSampleCount += retained;
      }
    }
  }

  speakerVadLength(): number {
    return this.speakerVadSampleCount;
  }

  speakerVadTail(n: number): Float32Array {
    const all = concatFloat32(this.speakerVadParts, this.speakerVadSampleCount);
    if (all.length <= n) return all;
    return all.slice(all.length - n, all.length);
  }

  fallbackSamples(): Float32Array {
    return concatFloat32(this.fallbackParts, this.fallbackSampleCount);
  }

  clearNativeSegment(): void {
    this.speakerVadParts = [];
    this.speakerVadSampleCount = 0;
  }

  clearPublicUtterance(): void {
    this.fallbackParts = [];
    this.fallbackSampleCount = 0;
  }

  clearAll(): void {
    this.clearNativeSegment();
    this.clearPublicUtterance();
  }
}

function concatFloat32(parts: Float32Array[], total: number): Float32Array {
  const out = new Float32Array(total);
  let offset = 0;
  for (let i = 0; i < parts.length; i++) {
    out.set(parts[i], offset);
    offset += parts[i].length;
  }
  return out;
}
