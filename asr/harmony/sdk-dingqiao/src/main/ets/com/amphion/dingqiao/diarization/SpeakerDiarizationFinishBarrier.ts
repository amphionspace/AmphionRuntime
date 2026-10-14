export interface SpeakerDiarizationFinishInput<T> {
  degraded: boolean;
  value: T;
}

export interface SpeakerDiarizationFinishOutput<A, S> {
  asr: A;
  speaker: S | undefined;
  degraded: boolean;
}

/** Elapsed milliseconds from stop, for the one metric that explains a slow finish. */
export interface SpeakerDiarizationFinishTimings {
  stopToAsrTailMs: number;
  stopToSalvageMs: number;
  stopToSpeakerMs: number;
  asrTailToSpeakerMs: number;
  salvaged: boolean;
  timedOut: boolean;
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
  private readonly deadlineMs: number;
  private readonly onReady: (result: SpeakerDiarizationFinishOutput<A, S>) => void;
  private readonly salvageReserveMs: number;
  private readonly onTimeout?: () => void;
  private beganAtMs: number = 0;
  private asrAtMs: number = 0;
  private salvageAtMs: number = 0;
  private speakerAtMs: number = 0;
  private timedOut: boolean = false;
  private deadlinePassed: boolean = false;

  // The deadline is measured from stop, not from the ASR tail, because that is
  // the interval a caller measures: stop the recording, wait for roles. The
  // reserve is carved out of it rather than added to it, so the whole finish
  // costs at most deadlineMs after stop. ASR is exempt by design - it must
  // drain every accepted frame, and dropping that would drop recognized text -
  // so the public callback still waits for the tail and the real bound is
  // max(ASR drain, deadlineMs).
  //
  // The cost of anchoring at stop: a slow ASR drain now eats the clustering
  // budget instead of extending it, so a backlogged recognizer truncates the
  // meeting's tail roles sooner. That is a property of the backlog, not of this
  // budget; bounding the window queue is what fixes it.
  //
  // One exception, because it would be loss for nothing: when the deadline
  // passes with ASR still draining, the callback is blocked on ASR anyway, so
  // freezing diarization there buys no latency and only drops roles. The
  // deadline is recorded as passed and the salvage waits for the tail, which
  // leaves clustering the time it was going to spend blocked regardless. Where
  // the deadline is achievable - the tail inside it - this changes nothing.
  constructor(
    deadlineMs: number,
    onReady: (result: SpeakerDiarizationFinishOutput<A, S>) => void,
    salvageReserveMs: number = 0,
    onTimeout?: () => void,
  ) {
    if (deadlineMs <= 0) {
      throw new Error('deadlineMs must be positive');
    }
    if (salvageReserveMs < 0) {
      throw new Error('salvageReserveMs must not be negative');
    }
    if (salvageReserveMs >= deadlineMs) {
      throw new Error('salvageReserveMs must leave room inside deadlineMs');
    }
    this.deadlineMs = deadlineMs;
    this.onReady = onReady;
    this.salvageReserveMs = salvageReserveMs;
    this.onTimeout = onTimeout;
  }

  begin(): void {
    if (this.started || this.completed) {
      return;
    }
    this.started = true;
    this.beganAtMs = Date.now();
    this.armDeadline();
  }

  private armDeadline(): void {
    if (!this.started || this.speakerReady || this.completed || this.timer !== undefined) return;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      if (this.completed || this.speakerReady) {
        return;
      }
      this.timedOut = true;
      if (!this.asrReady) {
        // Blocked on ASR: salvaging here would drop roles and save nothing.
        this.deadlinePassed = true;
        return;
      }
      this.beginSalvage();
    }, this.deadlineMs - this.salvageReserveMs);
  }

  private beginSalvage(): void {
    if (this.completed || this.speakerReady || this.timer !== undefined) return;
    if (this.salvageReserveMs > 0) {
      this.salvageAtMs = Date.now();
      this.timer = setTimeout(() => {
        this.timer = undefined;
        this.expire();
      }, this.salvageReserveMs);
      this.onTimeout?.();
      return;
    }
    this.expire();
  }

  private expire(): void {
    if (this.completed || this.speakerReady) {
      return;
    }
    this.speakerReady = true;
    this.speakerAtMs = Date.now();
    this.degraded = true;
    // Only diarization may degrade on timeout. ASR must drain all accepted audio.
    this.tryComplete();
  }

  resolveAsr(value: A): void {
    if (this.completed || this.asrReady) {
      return;
    }
    this.asrReady = true;
    this.asrAtMs = Date.now();
    this.asrValue = value;
    this.tryComplete();
    // The deadline was spent waiting for this tail. Settle diarization now, with
    // the reserve it was owed, rather than having abandoned it while blocked.
    if (!this.completed && this.deadlinePassed) this.beginSalvage();
  }

  hasAsrTail(): boolean { return this.asrReady; }

  resolveSpeaker(result: SpeakerDiarizationFinishInput<S>): void {
    if (this.completed || this.speakerReady) {
      return;
    }
    this.speakerReady = true;
    this.speakerAtMs = Date.now();
    this.speakerValue = result.value;
    this.degraded = result.degraded;
    this.tryComplete();
  }

  /** Valid once begin() has run; unreached stages report -1 rather than a fake 0. */
  timings(): SpeakerDiarizationFinishTimings {
    const since = (at: number): number => at > 0 && this.beganAtMs > 0 ? at - this.beganAtMs : -1;
    const stopToAsrTailMs = since(this.asrAtMs);
    const stopToSpeakerMs = since(this.speakerAtMs);
    return {
      stopToAsrTailMs,
      stopToSalvageMs: since(this.salvageAtMs),
      stopToSpeakerMs,
      asrTailToSpeakerMs: stopToAsrTailMs >= 0 && stopToSpeakerMs >= 0 ?
        stopToSpeakerMs - stopToAsrTailMs : -1,
      salvaged: this.salvageAtMs > 0,
      timedOut: this.timedOut,
    };
  }

  /**
   * Drop a deadline a torn-down session will never answer.
   *
   * The deadline is armed at stop, so a session cancelled before its ASR tail
   * leaves it pending: it would fire into a finished session, do nothing, and
   * hold this closure until then. Teardown owns it.
   */
  dispose(): void {
    this.completed = true;
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
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
