export interface SessionAudioProcessor {
  write(audio: ArrayBuffer): Promise<void>;
  writeFloat(samples: Float32Array): Promise<void>;
  finish(): Promise<void>;
}

/**
 * Serializes public audio submissions without running recognition work in the
 * caller's writeAudio stack. Frames are snapshotted before returning because
 * microphone integrations commonly reuse their capture buffers.
 */
export class SessionAudioDispatcher {
  private static executionTail: Promise<void> = Promise.resolve();
  private processor: SessionAudioProcessor;
  private onError: (message: string) => void;
  private pending: Promise<void> = Promise.resolve();
  private accepting: boolean = true;
  private canceled: boolean = false;
  private failed: boolean = false;
  private finishTask?: Promise<void>;

  constructor(processor: SessionAudioProcessor, onError: (message: string) => void) {
    this.processor = processor;
    this.onError = onError;
  }

  write(audio: ArrayBuffer): boolean {
    if (!this.accepting || this.canceled || this.failed || audio.byteLength === 0) return false;
    const snapshot = audio.slice(0);
    this.enqueue(async (): Promise<void> => {
      if (this.canceled || this.failed) return;
      try {
        await this.processor.write(snapshot);
      } catch (e) {
        this.fail(`${e}`);
      }
    });
    return true;
  }

  writeFloat(samples: Float32Array): boolean {
    if (!this.accepting || this.canceled || this.failed || samples.length === 0) return false;
    const snapshot = samples.slice();
    this.enqueue(async (): Promise<void> => {
      if (this.canceled || this.failed) return;
      try {
        await this.processor.writeFloat(snapshot);
      } catch (e) {
        this.fail(`${e}`);
      }
    });
    return true;
  }

  finish(): Promise<void> {
    if (this.finishTask !== undefined) return this.finishTask;
    if (this.canceled) return Promise.resolve();
    this.accepting = false;
    this.enqueue(async (): Promise<void> => {
      if (this.canceled || this.failed) return;
      try {
        await this.processor.finish();
      } catch (e) {
        this.fail(`${e}`);
      }
    });
    this.finishTask = this.pending;
    return this.finishTask;
  }

  cancel(): void {
    this.accepting = false;
    this.canceled = true;
  }

  whenIdle(): Promise<void> {
    return this.pending;
  }

  private enqueue(task: () => Promise<void>): void {
    const sessionPredecessor = this.pending;
    const execution = SessionAudioDispatcher.executionTail.then(async (): Promise<void> => {
      await sessionPredecessor;
      await task();
    });
    this.pending = execution;
    SessionAudioDispatcher.executionTail = execution.catch((): void => {});
  }

  private fail(message: string): void {
    if (this.failed || this.canceled) return;
    this.failed = true;
    this.accepting = false;
    this.onError(message);
  }
}
