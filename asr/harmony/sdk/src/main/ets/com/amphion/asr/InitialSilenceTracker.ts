const ACOUSTIC_WINDOWS_PER_SECOND: number = 50;
const RECENT_ACTIVITY_MS: number = 300;
const ACTIVE_RMS_THRESHOLD: number = 0.01;
const REQUIRED_ACTIVE_WINDOWS: number = 3;
const MIN_SPEECH_ZCR: number = 0.005;
const MAX_SPEECH_ZCR: number = 0.35;
const MIN_SPEECH_ENERGY_RATIO: number = 3;

export class InitialSilenceTracker {
  private thresholdSamples: number;
  private confirmationGraceSamples: number;
  private deadlineSamples: number;
  private silenceSamples: number = 0;
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
  private consecutiveSpeechLikeWindows: number = 0;
  private speechLikeMinRms: number = Number.MAX_VALUE;
  private speechLikeMaxRms: number = 0;
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
    this.silenceSamples = 0;
  }

  observeAsrResult(text: string, tokenCount: number): void {
    if (text.length > 0 || tokenCount > 0) this.markSpeechDetected();
  }

  observeAcousticSamples(samples: Float32Array): void {
    if (this.timeoutSent || this.speechDetected || this.thresholdSamples === 0 ||
      this.confirmationGraceSamples === 0) return;
    for (let i = 0; i < samples.length; i++) {
      this.acousticSquareSum += samples[i] * samples[i];
      if (this.hasPreviousSample && (samples[i] >= 0) !== (this.previousSample >= 0)) {
        this.zeroCrossingsInWindow += 1;
      }
      this.previousSample = samples[i];
      this.hasPreviousSample = true;
      this.samplesInAcousticWindow += 1;
      if (this.samplesInAcousticWindow < this.acousticWindowSamples) continue;

      const rms = Math.sqrt(this.acousticSquareSum / this.samplesInAcousticWindow);
      const active = rms >= ACTIVE_RMS_THRESHOLD;
      this.consecutiveActiveWindows = active ? this.consecutiveActiveWindows + 1 : 0;
      if (this.consecutiveActiveWindows >= REQUIRED_ACTIVE_WINDOWS) {
        this.samplesSinceActivity = 0;
      } else if (this.samplesSinceActivity !== Number.MAX_SAFE_INTEGER) {
        this.samplesSinceActivity += this.samplesInAcousticWindow;
      }
      const zcr = this.zeroCrossingsInWindow / Math.max(1, this.samplesInAcousticWindow - 1);
      const speechLikeWindow = active && zcr >= MIN_SPEECH_ZCR && zcr <= MAX_SPEECH_ZCR;
      if (speechLikeWindow) {
        this.consecutiveSpeechLikeWindows += 1;
        this.speechLikeMinRms = Math.min(this.speechLikeMinRms, rms);
        this.speechLikeMaxRms = Math.max(this.speechLikeMaxRms, rms);
        if (this.consecutiveSpeechLikeWindows >= REQUIRED_ACTIVE_WINDOWS &&
          this.speechLikeMaxRms >= this.speechLikeMinRms * MIN_SPEECH_ENERGY_RATIO) {
          this.speechLikeActivityDetected = true;
          this.samplesSinceSpeechLikeActivity = 0;
        }
      } else {
        this.consecutiveSpeechLikeWindows = 0;
        this.speechLikeMinRms = Number.MAX_VALUE;
        this.speechLikeMaxRms = 0;
      }
      if (this.samplesSinceSpeechLikeActivity !== Number.MAX_SAFE_INTEGER &&
        this.samplesSinceSpeechLikeActivity !== 0) {
        this.samplesSinceSpeechLikeActivity += this.samplesInAcousticWindow;
      } else if (this.samplesSinceSpeechLikeActivity === 0 && !speechLikeWindow) {
        this.samplesSinceSpeechLikeActivity += this.samplesInAcousticWindow;
      }
      this.acousticSquareSum = 0;
      this.samplesInAcousticWindow = 0;
      this.zeroCrossingsInWindow = 0;
      this.hasPreviousSample = false;
    }
  }

  observeVad(processedSamples: number, speechDetected: boolean): boolean {
    if (this.timeoutSent || this.speechDetected || this.thresholdSamples === 0) return false;
    if (speechDetected) {
      this.markSpeechDetected();
      return false;
    }
    this.silenceSamples += Math.max(0, processedSamples);
    if (this.silenceSamples < this.deadlineSamples) return false;

    if (!this.graceGranted && this.confirmationGraceSamples > 0 &&
      (this.samplesSinceActivity <= this.recentActivitySamples || this.hasSpeechLikeActivity())) {
      this.graceGranted = true;
      this.deadlineSamples += this.confirmationGraceSamples;
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

  confirmTimeout(): boolean {
    if (this.timeoutSent || this.speechDetected) return false;
    this.timeoutSent = true;
    return true;
  }

  hasTimedOut(): boolean {
    return this.timeoutSent;
  }
}
