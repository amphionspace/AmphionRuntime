/** Callbacks shared by the on-device and cloud recognizers, so the page renders both identically. */
export interface RecognizerEvents {
  onListening(): void;
  /**
   * confirmed=false marks a preview not yet attributed to the enrolled speaker: it is shown light and
   * never settles until confirmed, and is withdrawn via onFiltered if it turns out to be someone else.
   */
  onPartial(text: string, confirmed?: boolean): void;
  /**
   * similarity is reported by the on-device engine only; undefined means "not scored".
   * startSample/endSample locate the sentence in the audio written to this session (16 kHz), when the
   * engine reports an exact range; otherwise the caller derives the range from its own audio clock.
   */
  onFinal(text: string, similarity?: number, startSample?: number, endSample?: number): void;
  /** A span was attributed to someone other than the enrolled speaker and withheld. */
  onFiltered(): void;
  onComplete(): void;
  onError(message: string): void;
}

export interface TargetRecognizer {
  /** Starts a session; audio written before the session is ready is buffered, not dropped. */
  start(events: RecognizerEvents): void;
  /** 640-byte, 20 ms, 16 kHz mono PCM16 frames. */
  write(frame: ArrayBuffer): void;
  /** Ends input and waits for the remaining results; onComplete fires afterwards. */
  finish(): void;
  /** Drops the session without waiting for results. */
  cancel(): void;
}
