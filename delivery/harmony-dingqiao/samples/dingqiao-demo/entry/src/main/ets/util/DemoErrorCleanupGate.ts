/** Prevents a replacement session from starting while the failed recorder is still draining. */
export class DemoErrorCleanupGate {
  private cleanupInProgress: boolean = false;

  canStart(): boolean {
    return !this.cleanupInProgress;
  }

  tryBeginCleanup(): boolean {
    if (this.cleanupInProgress) return false;
    this.cleanupInProgress = true;
    return true;
  }

  finishCleanup(): void {
    this.cleanupInProgress = false;
  }
}
