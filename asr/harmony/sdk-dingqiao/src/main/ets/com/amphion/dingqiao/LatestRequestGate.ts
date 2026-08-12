/** Monotonic latest-wins token used across asynchronous license validation and Runtime drain. */
export class LatestRequestGate {
  private generation: number = 0;

  begin(): number {
    this.generation += 1;
    return this.generation;
  }

  invalidate(): void {
    this.generation += 1;
  }

  isCurrent(request: number): boolean {
    return request === this.generation;
  }
}
