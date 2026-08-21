export type SpeakerInferenceTask<T> = () => Promise<T>;
export type SpeakerInferenceResult<T> = (value: T) => void;
export type SpeakerInferenceError = (error: Object) => void;

/**
 * A session-local FIFO for expensive speaker work.
 *
 * submit() never waits for native inference, so PCM/VAD can continue on the caller lane. A
 * generation token makes reset/cancel cheap: late native completions retain their native leases,
 * but cannot mutate the next utterance.
 */
export class SpeakerInferenceLane {
  private generationValue: number = 1;
  private tail: Promise<void> = Promise.resolve();
  private pendingValue: number = 0;

  generation(): number { return this.generationValue; }
  isCurrent(generation: number): boolean { return generation === this.generationValue; }
  pending(): number { return this.pendingValue; }

  submit<T>(generation: number, task: SpeakerInferenceTask<T>,
    apply: SpeakerInferenceResult<T>, reject?: SpeakerInferenceError): void {
    this.pendingValue += 1;
    const run = async (): Promise<void> => {
      try {
        const value = await task();
        if (generation === this.generationValue) apply(value);
      } catch (e) {
        if (generation === this.generationValue && reject !== undefined) reject(e as Object);
      } finally {
        this.pendingValue = Math.max(0, this.pendingValue - 1);
      }
    };
    this.tail = this.tail.then(run, run);
  }

  async drain(generation: number = this.generationValue): Promise<void> {
    // Tasks may append continuations while an earlier snapshot is settling.
    while (generation === this.generationValue) {
      const snapshot = this.tail;
      await snapshot;
      if (snapshot === this.tail) return;
    }
  }

  async whenIdle(): Promise<void> {
    // Invalidated work cannot apply results, but it still owns native leases until it settles.
    while (true) {
      const snapshot = this.tail;
      await snapshot;
      if (snapshot === this.tail && this.pendingValue === 0) return;
    }
  }

  invalidate(): number {
    this.generationValue += 1;
    return this.generationValue;
  }
}
