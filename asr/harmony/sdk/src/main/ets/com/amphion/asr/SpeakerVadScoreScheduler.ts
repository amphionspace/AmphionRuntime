/**
 * Anchors Speaker VAD score deadlines to absolute PCM sample positions in one native segment.
 *
 * The runtime stops each internal feed at samplesUntilNextScore(), then calls observe(). This keeps
 * the score timeline independent of how public writeAudio calls partition the same PCM.
 */
export class SpeakerVadScoreScheduler {
  readonly windowSamples: number;
  readonly hopSamples: number;
  private consumedSamples: number = 0;
  private firstScoreSample: number;
  private nextScoreSample: number;

  constructor(windowSamples: number, hopSamples: number) {
    this.windowSamples = Math.round(windowSamples);
    this.hopSamples = Math.round(hopSamples);
    if (this.windowSamples <= 0) throw new Error('windowSamples must be > 0');
    if (this.hopSamples <= 0) throw new Error('hopSamples must be > 0');
    this.firstScoreSample = Math.max(this.windowSamples, this.hopSamples);
    this.nextScoreSample = this.firstScoreSample;
  }

  totalSamples(): number {
    return this.consumedSamples;
  }

  samplesUntilNextScore(): number {
    return Math.max(1, this.nextScoreSample - this.consumedSamples);
  }

  /** Returns true exactly when the accepted slice ends at a score deadline. */
  observe(samples: number): boolean {
    const accepted = Math.round(samples);
    if (accepted < 0) throw new Error('samples must be >= 0');
    if (accepted > this.samplesUntilNextScore()) {
      throw new Error('accepted slice crosses Speaker VAD score deadline');
    }
    this.consumedSamples += accepted;
    if (this.consumedSamples !== this.nextScoreSample) return false;

    if (this.nextScoreSample === this.firstScoreSample) {
      const remainder = this.firstScoreSample % this.hopSamples;
      this.nextScoreSample += remainder === 0 ? this.hopSamples : this.hopSamples - remainder;
    } else {
      this.nextScoreSample += this.hopSamples;
    }
    return true;
  }

  reset(): void {
    this.consumedSamples = 0;
    this.nextScoreSample = this.firstScoreSample;
  }
}
