export interface SpeakerDiarizationFinishInput<T> {
  degraded: boolean;
  value: T;
}

export interface SpeakerDiarizationFinishOutput<A, S> {
  asr: A;
  speaker: S | undefined;
  degraded: boolean;
}

/** Coordinates the ASR tail and streaming diarization tail without blocking finish(). */
export class SpeakerDiarizationFinishBarrier<A, S> {
  private started: boolean = false;
  private completed: boolean = false;
  private asrReady: boolean = false;
  private speakerReady: boolean = false;
  private degraded: boolean = false;
  private asrValue?: A;
  private speakerValue?: S;
  private timer?: ReturnType<typeof setTimeout>;
  private readonly timeoutMs: number;
  private readonly onReady: (result: SpeakerDiarizationFinishOutput<A, S>) => void;
  private readonly salvageMs: number;
  private readonly onTimeout?: () => void;

  // On timeout, first ask diarization to freeze what it already inferred, and wait at
  // most salvageMs for that result before completing without speaker results.
  constructor(
    timeoutMs: number,
    onReady: (result: SpeakerDiarizationFinishOutput<A, S>) => void,
    salvageMs: number = 0,
    onTimeout?: () => void,
  ) {
    if (timeoutMs <= 0) {
      throw new Error('timeoutMs must be positive');
    }
    if (salvageMs < 0) {
      throw new Error('salvageMs must not be negative');
    }
    this.timeoutMs = timeoutMs;
    this.onReady = onReady;
    this.salvageMs = salvageMs;
    this.onTimeout = onTimeout;
  }

  begin(): void {
    if (this.started || this.completed) {
      return;
    }
    this.started = true;
    this.startTimeoutIfReady();
  }

  private startTimeoutIfReady(): void {
    // Diarization also waits for the real ASR tail. Its timeout must not include ASR backlog.
    if (!this.started || !this.asrReady || this.speakerReady || this.completed ||
      this.timer !== undefined) return;
    this.timer = setTimeout(() => {
      if (this.completed || this.speakerReady) {
        return;
      }
      if (this.salvageMs > 0) {
        this.timer = setTimeout(() => this.expire(), this.salvageMs);
        this.onTimeout?.();
        return;
      }
      this.expire();
    }, this.timeoutMs);
  }

  private expire(): void {
    if (this.completed || this.speakerReady) {
      return;
    }
    this.speakerReady = true;
    this.degraded = true;
    // Only diarization may degrade on timeout. ASR must drain all accepted audio.
    this.tryComplete();
  }

  resolveAsr(value: A): void {
    if (this.completed || this.asrReady) {
      return;
    }
    this.asrReady = true;
    this.asrValue = value;
    this.startTimeoutIfReady();
    this.tryComplete();
  }

  hasAsrTail(): boolean { return this.asrReady; }

  resolveSpeaker(result: SpeakerDiarizationFinishInput<S>): void {
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
