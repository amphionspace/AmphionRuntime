export interface DiarizationCommitBoundary {
  beginTime: number;
  endTime: number;
  evidenceEndTime: number;
}

/** Audio-time decisions are independent of which inference/callback queue happens to run first. */
export class DiarizationCommitClock {
  private plannedThrough: number = 0;
  private committedThrough: number = 0;
  private readonly pending: DiarizationCommitBoundary[] = [];

  observeEndpoint(endTime: number): void {
    if (endTime < this.plannedThrough + 120000) return;
    this.pending.push({
      beginTime: this.plannedThrough,
      endTime,
      evidenceEndTime: Math.ceil((endTime + 1500) / 2500) * 2500,
    });
    this.plannedThrough = endTime;
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
