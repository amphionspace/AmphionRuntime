/**
 * Keeps a finish that has already been accepted alive when a legacy host calls shutdown before
 * final/onComplete arrives. Non-finishing shutdown remains immediate and repeated calls are
 * idempotent.
 */
export class FinishShutdownGate {
  private release: () => void;
  private requested: boolean = false;
  private released: boolean = false;

  constructor(release: () => void) {
    this.release = release;
  }

  request(finishing: boolean): boolean {
    if (this.requested) return !this.released && finishing;
    this.requested = true;
    if (!finishing) this.releaseOnce();
    return finishing;
  }

  settle(): void {
    if (this.requested) this.releaseOnce();
  }

  private releaseOnce(): void {
    if (this.released) return;
    this.released = true;
    this.release();
  }
}
