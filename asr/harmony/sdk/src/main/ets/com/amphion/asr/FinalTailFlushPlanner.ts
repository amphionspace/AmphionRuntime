/**
 * Bounds manual-finish padding while counting real encoder decode opportunities.
 *
 * The caller owns recognizer readiness. It appends nextPaddingMs() when the stream is not ready,
 * or records exactly one decode after running a single ready chunk. Synthetic padding never flows
 * through the public PCM, VAD, Speaker VAD, or speaker-scoring buffers.
 */
export class FinalTailFlushPlanner {
  readonly stepMs: number;
  readonly maxPaddingMs: number;
  readonly requiredDecodes: number;
  private paddedMs: number = 0;
  private decodedChunks: number = 0;

  constructor(stepMs: number, maxPaddingMs: number, requiredDecodes: number) {
    this.stepMs = Math.round(stepMs);
    this.maxPaddingMs = Math.round(maxPaddingMs);
    this.requiredDecodes = Math.round(requiredDecodes);
    if (this.stepMs <= 0) throw new Error('stepMs must be > 0');
    if (this.maxPaddingMs <= 0) throw new Error('maxPaddingMs must be > 0');
    if (this.requiredDecodes <= 0) throw new Error('requiredDecodes must be > 0');
  }

  isComplete(): boolean {
    return this.decodedChunks >= this.requiredDecodes;
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
    if (this.isComplete()) throw new Error('final tail flush is already complete');
    this.decodedChunks += 1;
  }

  paddingDurationMs(): number {
    return this.paddedMs;
  }

  decodeOpportunities(): number {
    return this.decodedChunks;
  }

  usedFallback(): boolean {
    return this.paddedMs >= this.maxPaddingMs && this.decodedChunks < this.requiredDecodes;
  }
}
