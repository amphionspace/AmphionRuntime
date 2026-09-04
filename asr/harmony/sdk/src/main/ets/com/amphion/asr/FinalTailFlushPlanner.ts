/**
 * Bounds manual-finish padding while counting real encoder decode opportunities.
 *
 * The caller owns recognizer readiness. It appends nextPaddingMs() when the stream is not ready,
 * or records exactly one decode after running a single ready chunk. A first chunk may complete the
 * flush only when it already contains the configured amount of synthetic right context; otherwise
 * the caller must decode a second chunk. Synthetic padding never flows through the public PCM, VAD,
 * Speaker VAD, or speaker-scoring buffers.
 */
export class FinalTailFlushPlanner {
  readonly stepMs: number;
  readonly maxPaddingMs: number;
  readonly requiredDecodes: number;
  readonly singleDecodeMinPaddingMs: number;
  private paddedMs: number = 0;
  private decodedChunks: number = 0;
  private firstDecodePaddedMs: number = -1;

  constructor(stepMs: number, maxPaddingMs: number, requiredDecodes: number,
    singleDecodeMinPaddingMs: number = 0) {
    this.stepMs = Math.round(stepMs);
    this.maxPaddingMs = Math.round(maxPaddingMs);
    this.requiredDecodes = Math.round(requiredDecodes);
    this.singleDecodeMinPaddingMs = Math.round(singleDecodeMinPaddingMs);
    if (this.stepMs <= 0) throw new Error('stepMs must be > 0');
    if (this.maxPaddingMs <= 0) throw new Error('maxPaddingMs must be > 0');
    if (this.requiredDecodes <= 0) throw new Error('requiredDecodes must be > 0');
    if (this.singleDecodeMinPaddingMs < 0 || this.singleDecodeMinPaddingMs > this.maxPaddingMs) {
      throw new Error('singleDecodeMinPaddingMs must be within the padding bound');
    }
  }

  isComplete(): boolean {
    return this.decodedChunks >= this.requiredDecodes ||
      (this.decodedChunks >= 1 && this.singleDecodeMinPaddingMs > 0 &&
        this.firstDecodePaddedMs >= this.singleDecodeMinPaddingMs);
  }

  nextPaddingMs(): number {
    if (this.isComplete() || this.paddedMs >= this.maxPaddingMs) return 0;
    return Math.min(this.stepMs, this.maxPaddingMs - this.paddedMs);
  }

  recordPadding(durationMs: number): void {
    const accepted = Math.round(durationMs);
    const expected = this.nextPaddingMs();
    if (accepted <= 0 || accepted !== expected) {
      throw new Error(`padding must match nextPaddingMs: ${accepted} != ${expected}`);
    }
    this.paddedMs += accepted;
  }

  recordDecode(): void {
    if (this.isComplete()) {
      throw new Error('final tail flush is already complete');
    }
    if (this.decodedChunks === 0) this.firstDecodePaddedMs = this.paddedMs;
    this.decodedChunks += 1;
  }

  paddingDurationMs(): number {
    return this.paddedMs;
  }

  decodeOpportunities(): number {
    return this.decodedChunks;
  }

  usedFallback(): boolean {
    return this.paddedMs >= this.maxPaddingMs && !this.isComplete();
  }
}
