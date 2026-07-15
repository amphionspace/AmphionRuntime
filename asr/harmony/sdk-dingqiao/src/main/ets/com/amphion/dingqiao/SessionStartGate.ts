export class SessionStartGate {
  private generation: number = 0;
  private nativeStarted: boolean = false;
  private sessionPublished: boolean = false;
  private delivered: boolean = false;

  begin(): number {
    this.generation += 1;
    this.clearSignals();
    return this.generation;
  }

  reset(): void {
    this.generation += 1;
    this.clearSignals();
  }

  observeNativeStarted(generation: number): boolean {
    if (generation !== this.generation) return false;
    this.nativeStarted = true;
    return this.claimDelivery();
  }

  publishSession(generation: number): boolean {
    if (generation !== this.generation) return false;
    this.sessionPublished = true;
    return this.claimDelivery();
  }

  private clearSignals(): void {
    this.nativeStarted = false;
    this.sessionPublished = false;
    this.delivered = false;
  }

  private claimDelivery(): boolean {
    if (!this.nativeStarted || !this.sessionPublished || this.delivered) return false;
    this.delivered = true;
    return true;
  }
}
