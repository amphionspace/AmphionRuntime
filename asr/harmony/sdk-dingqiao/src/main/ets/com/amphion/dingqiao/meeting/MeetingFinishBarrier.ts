export interface MeetingFinishInput<T> {
  degraded: boolean;
  value: T;
}

export interface MeetingFinishOutput<A, S> {
  asr: A;
  speaker: S | undefined;
  degraded: boolean;
}

/** Coordinates the ASR tail and meeting diarization tail without blocking finish(). */
export class MeetingFinishBarrier<A, S> {
  private started: boolean = false;
  private completed: boolean = false;
  private asrReady: boolean = false;
  private speakerReady: boolean = false;
  private degraded: boolean = false;
  private asrValue?: A;
  private speakerValue?: S;
  private timer?: ReturnType<typeof setTimeout>;
  private readonly timeoutMs: number;
  private readonly onReady: (result: MeetingFinishOutput<A, S>) => void;
  private readonly timeoutAsrFallback?: () => A;

  constructor(
    timeoutMs: number,
    onReady: (result: MeetingFinishOutput<A, S>) => void,
    timeoutAsrFallback?: () => A,
  ) {
    if (timeoutMs <= 0) {
      throw new Error('timeoutMs must be positive');
    }
    this.timeoutMs = timeoutMs;
    this.onReady = onReady;
    this.timeoutAsrFallback = timeoutAsrFallback;
  }

  begin(): void {
    if (this.started || this.completed) {
      return;
    }
    this.started = true;
    this.timer = setTimeout(() => {
      if (this.completed) {
        return;
      }
      this.speakerReady = true;
      this.degraded = true;
      if (!this.asrReady && this.timeoutAsrFallback !== undefined) {
        this.asrValue = this.timeoutAsrFallback();
        this.asrReady = true;
      }
      this.tryComplete();
    }, this.timeoutMs);
  }

  resolveAsr(value: A): void {
    if (this.completed || this.asrReady) {
      return;
    }
    this.asrReady = true;
    this.asrValue = value;
    this.tryComplete();
  }

  resolveSpeaker(result: MeetingFinishInput<S>): void {
    if (this.completed || this.speakerReady) {
      return;
    }
    this.speakerReady = true;
    this.speakerValue = result.value;
    this.degraded = result.degraded;
    this.tryComplete();
  }

  private tryComplete(): void {
    if (this.completed || !this.asrReady || !this.speakerReady) {
      return;
    }
    this.completed = true;
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    this.onReady({
      asr: this.asrValue as A,
      speaker: this.speakerValue,
      degraded: this.degraded,
    });
  }
}
