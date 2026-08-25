export interface DiarizationInferenceWindow {
  startSample: number;
  endSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
}

/**
 * Produces frame-independent 10 s / 2.5 s streaming diarization windows.
 *
 * Early windows have less than 10 seconds of real audio and are left-padded by
 * the process client. realEndSample always bounds every public result.
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
    hopMs: number = 2_500,
    rightContextMs: number = 1_500,
  ) {
    if (sampleRate <= 0 || windowMs <= 0 || hopMs <= 0 || rightContextMs < 0) {
      throw new Error('Invalid diarization window configuration');
    }
    this.windowSamples = Math.round(sampleRate * windowMs / 1_000);
    this.hopSamples = Math.round(sampleRate * hopMs / 1_000);
    this.rightContextSamples = Math.round(sampleRate * rightContextMs / 1_000);
    this.nextWindowEnd = this.hopSamples;
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

  finish(): DiarizationInferenceWindow {
    if (this.finished) {
      throw new Error('Diarization window scheduler is already finished');
    }
    this.finished = true;

    const endSample = Math.max(this.totalSamples, this.windowSamples);
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
