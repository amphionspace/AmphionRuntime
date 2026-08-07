export interface ColdStartEngineDecision {
  accepted: boolean;
  finishAfterFlush: boolean;
}

/** Coordinates PTT release, recorder-tail flush, and asynchronous model load. */
export class ColdStartPttGate {
  private generation: number = 0;
  private activeGeneration: number = -1;
  private released: boolean = false;
  private captureDrained: boolean = false;
  private ready: boolean = false;

  begin(): number {
    this.generation += 1;
    this.activeGeneration = this.generation;
    this.released = false;
    this.captureDrained = false;
    this.ready = false;
    return this.activeGeneration;
  }

  release(generation: number): boolean {
    if (generation !== this.activeGeneration) return false;
    this.released = true;
    return true;
  }

  captureStopped(generation: number): boolean {
    if (generation !== this.activeGeneration) return false;
    this.captureDrained = true;
    return this.claimFinish();
  }

  engineReady(generation: number): ColdStartEngineDecision {
    if (generation !== this.activeGeneration) {
      return { accepted: false, finishAfterFlush: false };
    }
    this.ready = true;
    return { accepted: true, finishAfterFlush: this.claimFinish() };
  }

  cancel(): void {
    this.generation += 1;
    this.activeGeneration = -1;
    this.released = false;
    this.captureDrained = false;
    this.ready = false;
  }

  private claimFinish(): boolean {
    if (!this.released || !this.captureDrained || !this.ready) return false;
    this.activeGeneration = -1;
    return true;
  }
}
