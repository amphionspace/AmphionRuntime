import {
  ACOUSTIC_WINDOWS_PER_SECOND,
  acousticRms,
  isAcousticallyActive,
  isSpeechShapedWindow,
  MIN_SPEECH_ENERGY_RATIO,
  REQUIRED_SPEECH_LIKE_WINDOWS
} from './EffectiveSpeechBuffer';

const RECENT_ACTIVITY_MS: number = 300;

export class InitialSilenceTracker {
  private thresholdSamples: number;
  private confirmationGraceSamples: number;
  private deadlineSamples: number;
  private audioSamplesObserved: number = 0;
  private vadSamplesProcessed: number = 0;
  private speechDetected: boolean = false;
  private timeoutSent: boolean = false;
  private graceGranted: boolean = false;

  private acousticWindowSamples: number;
  private recentActivitySamples: number;
  private acousticSquareSum: number = 0;
  private samplesInAcousticWindow: number = 0;
  private zeroCrossingsInWindow: number = 0;
  private previousSample: number = 0;
  private hasPreviousSample: boolean = false;
  private consecutiveActiveWindows: number = 0;
  private samplesSinceActivity: number = Number.MAX_SAFE_INTEGER;
  private recentSpeechLikeRms: number[] = [];
  private speechLikeActivityDetected: boolean = false;
  private samplesSinceSpeechLikeActivity: number = Number.MAX_SAFE_INTEGER;

  constructor(timeoutMs: number, sampleRate: number, confirmationGraceMs: number = 0) {
    this.thresholdSamples = Math.max(0, Math.round(timeoutMs * sampleRate / 1000));
    this.confirmationGraceSamples = Math.max(0, Math.round(confirmationGraceMs * sampleRate / 1000));
    this.deadlineSamples = this.thresholdSamples;
    this.acousticWindowSamples = Math.max(1, Math.round(sampleRate / ACOUSTIC_WINDOWS_PER_SECOND));
    this.recentActivitySamples = Math.max(1, Math.round(sampleRate * RECENT_ACTIVITY_MS / 1000));
  }

  markSpeechDetected(): void {
    this.speechDetected = true;
  }

  observeAsrResult(text: string, tokenCount: number): void {
    if ((text.length > 0 || tokenCount > 0) &&
      (this.thresholdSamples === 0 || this.evidenceSamplePosition() <= this.deadlineSamples)) {
      this.markSpeechDetected();
    }
  }

  observeAcousticSamples(samples: Float32Array): void {
    const observedBefore = this.audioSamplesObserved;
    this.audioSamplesObserved += samples.length;
    if (this.timeoutSent || this.speechDetected || this.thresholdSamples === 0 ||
      this.confirmationGraceSamples === 0) return;
    // The caller's frame may straddle the exact deadline. Only its prefix can influence the decision
    // at that deadline; a later grace grant starts from subsequent input rather than looking back.
    const eligibleSamples = Math.max(0, Math.min(samples.length, this.deadlineSamples - observedBefore));
    for (let i = 0; i < eligibleSamples; i++) {
      this.acousticSquareSum += samples[i] * samples[i];
      if (this.hasPreviousSample && (samples[i] >= 0) !== (this.previousSample >= 0)) {
        this.zeroCrossingsInWindow += 1;
      }
      this.previousSample = samples[i];
      this.hasPreviousSample = true;
      this.samplesInAcousticWindow += 1;
      if (this.samplesInAcousticWindow < this.acousticWindowSamples) continue;

      const rms = acousticRms(this.acousticSquareSum, this.samplesInAcousticWindow);
      const active = isAcousticallyActive(rms);
      this.consecutiveActiveWindows = active ? this.consecutiveActiveWindows + 1 : 0;
      if (this.consecutiveActiveWindows >= REQUIRED_SPEECH_LIKE_WINDOWS) {
        this.samplesSinceActivity = 0;
      } else if (this.samplesSinceActivity !== Number.MAX_SAFE_INTEGER) {
        this.samplesSinceActivity += this.samplesInAcousticWindow;
      }
      const zcr = this.zeroCrossingsInWindow / Math.max(1, this.samplesInAcousticWindow - 1);
      const speechLikeWindow = isSpeechShapedWindow(rms, zcr);
      if (this.samplesSinceSpeechLikeActivity !== Number.MAX_SAFE_INTEGER) {
        this.samplesSinceSpeechLikeActivity += this.samplesInAcousticWindow;
      }
      if (speechLikeWindow) {
        // Only fresh envelope variation refreshes recency; steady shaped windows must age out old evidence.
        this.recentSpeechLikeRms.push(rms);
        if (this.recentSpeechLikeRms.length > REQUIRED_SPEECH_LIKE_WINDOWS) {
          this.recentSpeechLikeRms.shift();
        }
        let minRms = Number.MAX_VALUE;
        let maxRms = 0;
        for (let j = 0; j < this.recentSpeechLikeRms.length; j++) {
          minRms = Math.min(minRms, this.recentSpeechLikeRms[j]);
          maxRms = Math.max(maxRms, this.recentSpeechLikeRms[j]);
        }
        if (this.recentSpeechLikeRms.length >= REQUIRED_SPEECH_LIKE_WINDOWS &&
          maxRms >= minRms * MIN_SPEECH_ENERGY_RATIO) {
          this.speechLikeActivityDetected = true;
          this.samplesSinceSpeechLikeActivity = 0;
        }
      } else {
        this.recentSpeechLikeRms = [];
      }
      this.acousticSquareSum = 0;
      this.samplesInAcousticWindow = 0;
      this.zeroCrossingsInWindow = 0;
      this.hasPreviousSample = false;
    }
  }

  observeVad(processedSamples: number, speechDetected: boolean): boolean {
    if (this.timeoutSent || this.speechDetected || this.thresholdSamples === 0) return false;
    const processed = Math.max(0, processedSamples);
    const evidenceWindowEnd = this.vadSamplesProcessed + processed;
    this.vadSamplesProcessed = evidenceWindowEnd;
    if (speechDetected && evidenceWindowEnd <= this.deadlineSamples) {
      this.markSpeechDetected();
      return false;
    }
    if (this.evidenceSamplePosition() < this.deadlineSamples) return false;

    if (!this.graceGranted && this.confirmationGraceSamples > 0 &&
      (this.samplesSinceActivity <= this.recentActivitySamples || this.hasSpeechLikeActivity())) {
      this.graceGranted = true;
      this.deadlineSamples += this.confirmationGraceSamples;
      // A VAD window that crossed the original deadline is valid only after independently observed
      // pre-deadline activity granted the bounded confirmation interval.
      if (speechDetected && evidenceWindowEnd <= this.deadlineSamples) this.markSpeechDetected();
      return false;
    }
    return true;
  }

  needsAsrProbe(): boolean {
    return this.graceGranted;
  }

  isArmed(): boolean {
    return !this.timeoutSent && !this.speechDetected && this.thresholdSamples > 0;
  }

  confirmSpeechLikeActivity(): boolean {
    if (!this.hasRecentSpeechLikeActivity()) return false;
    this.markSpeechDetected();
    return true;
  }

  private hasSpeechLikeActivity(): boolean {
    return this.speechLikeActivityDetected;
  }

  private hasRecentSpeechLikeActivity(): boolean {
    return this.samplesSinceSpeechLikeActivity <= this.recentActivitySamples;
  }

  private evidenceSamplePosition(): number {
    return Math.max(this.audioSamplesObserved, this.vadSamplesProcessed);
  }

  confirmTimeout(): boolean {
    if (this.timeoutSent || this.speechDetected) return false;
    this.timeoutSent = true;
    return true;
  }

  hasTimedOut(): boolean {
    return this.timeoutSent;
  }
}
