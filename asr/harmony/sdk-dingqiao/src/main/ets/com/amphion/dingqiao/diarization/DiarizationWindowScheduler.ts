export interface DiarizationInferenceWindow {
  startSample: number;
  endSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
}

/**
 * Community-1's frame-independent 10 s / 1 s windows, starting at sample zero.
 * Only the final incomplete window is padded, on the right. An exact final
 * full window must not be duplicated: that changes the VBx evidence density.
 */
export class DiarizationWindowScheduler {
  private readonly windowSamples: number;
  private readonly hopSamples: number;
  private readonly rightContextSamples: number;
  private totalSamples: number = 0;
  private nextWindowEnd: number;
  private committedThroughSample: number = 0;
  private finished: boolean = false;

  constructor(
    sampleRate: number,
    windowMs: number = 10_000,
    hopMs: number = 1_000,
    rightContextMs: number = 1_500,
  ) {
    if (sampleRate <= 0 || windowMs <= 0 || hopMs <= 0 || rightContextMs < 0) {
      throw new Error('Invalid diarization window configuration');
    }
    this.windowSamples = Math.round(sampleRate * windowMs / 1_000);
    this.hopSamples = Math.round(sampleRate * hopMs / 1_000);
    this.rightContextSamples = Math.round(sampleRate * rightContextMs / 1_000);
    this.nextWindowEnd = this.windowSamples;
  }

  acceptSamples(sampleCount: number): DiarizationInferenceWindow[] {
    if (this.finished) {
      throw new Error('Diarization window scheduler is already finished');
    }
    if (!Number.isInteger(sampleCount) || sampleCount < 0) {
      throw new Error('sampleCount must be a non-negative integer');
    }

    this.totalSamples += sampleCount;
    const windows: DiarizationInferenceWindow[] = [];
    while (this.totalSamples >= this.nextWindowEnd) {
      const endSample = this.nextWindowEnd;
      const stableEndSample = Math.max(endSample - this.rightContextSamples, 0);
      windows.push({
        startSample: Math.max(0, endSample - this.windowSamples),
        endSample,
        realEndSample: endSample,
        commitStartSample: this.committedThroughSample,
        stableEndSample,
        finalWindow: false,
      });
      this.committedThroughSample = stableEndSample;
      this.nextWindowEnd += this.hopSamples;
    }
    return windows;
  }

  finish(): DiarizationInferenceWindow | undefined {
    if (this.finished) {
      throw new Error('Diarization window scheduler is already finished');
    }
    this.finished = true;
    if (this.totalSamples === 0 || (this.nextWindowEnd > this.windowSamples &&
      this.totalSamples === this.nextWindowEnd - this.hopSamples)) return undefined;
    const endSample = this.nextWindowEnd;
    return {
      startSample: Math.max(endSample - this.windowSamples, 0),
      endSample,
      realEndSample: this.totalSamples,
      commitStartSample: this.committedThroughSample,
      stableEndSample: this.totalSamples,
      finalWindow: true,
    };
  }
}
