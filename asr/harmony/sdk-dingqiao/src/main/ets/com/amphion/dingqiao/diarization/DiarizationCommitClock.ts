export interface DiarizationCommitBoundary {
  beginTime: number;
  endTime: number;
  evidenceEndTime: number;
}

/** Audio-time decisions are independent of which inference/callback queue happens to run first. */
export class DiarizationCommitClock {
  private plannedThrough: number = 0;
  private committedThrough: number = 0;
  private processedThrough: number = 0;
  private endpoints: number[] = [];
  private readonly pending: DiarizationCommitBoundary[] = [];

  observeEndpoint(endTime: number): void {
    if (endTime > this.plannedThrough &&
      endTime > (this.endpoints[this.endpoints.length - 1] ?? 0)) this.endpoints.push(endTime);
  }

  /** Called only after ASR has returned all callbacks for the processed PCM. */
  observeProcessedAudio(endTime: number): boolean {
    this.processedThrough = Math.max(this.processedThrough, endTime);
    let queued = false;
    while (this.processedThrough >= this.plannedThrough + 120000) {
      const deadline = this.plannedThrough + 120000;
      let boundary: number | undefined;
      for (const endpoint of this.endpoints) {
        if (endpoint <= deadline) boundary = endpoint;
        else {
          // No completed sentence before the deadline: wait for the first one after it.
          if (boundary === undefined) boundary = endpoint;
          break;
        }
      }
      if (boundary === undefined || boundary > this.processedThrough) break;
      this.pending.push({ beginTime: this.plannedThrough, endTime: boundary,
        evidenceEndTime: Math.ceil((Math.max(deadline, boundary) + 1500) / 2500) * 2500 });
      this.plannedThrough = boundary;
      this.endpoints = this.endpoints.filter(endpoint => endpoint > boundary!);
      queued = true;
    }
    return queued;
  }

  takeReady(inferenceEndTime: number): DiarizationCommitBoundary | undefined {
    const next = this.pending[0];
    if (next === undefined || inferenceEndTime < next.evidenceEndTime) return undefined;
    this.pending.shift();
    this.committedThrough = next.endTime;
    return next;
  }

  beginTime(): number { return this.committedThrough; }
}
