export class InitialSilenceTracker {
  private thresholdSamples: number;
  private silenceSamples: number = 0;
  private speechDetected: boolean = false;
  private timeoutSent: boolean = false;

  constructor(timeoutMs: number, sampleRate: number) {
    this.thresholdSamples = Math.max(0, Math.round(timeoutMs * sampleRate / 1000));
  }

  markSpeechDetected(): void {
    this.speechDetected = true;
    this.silenceSamples = 0;
  }

  observeAsrResult(text: string, tokenCount: number): void {
    if (text.length > 0 || tokenCount > 0) this.markSpeechDetected();
  }

  observeVad(processedSamples: number, speechDetected: boolean): boolean {
    if (this.timeoutSent || this.speechDetected || this.thresholdSamples === 0) return false;
    if (speechDetected) {
      this.markSpeechDetected();
      return false;
    }
    this.silenceSamples += Math.max(0, processedSamples);
    if (this.silenceSamples < this.thresholdSamples) return false;
    this.timeoutSent = true;
    return true;
  }

  hasTimedOut(): boolean {
    return this.timeoutSent;
  }
}
