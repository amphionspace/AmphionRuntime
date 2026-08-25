export interface SessionAudioProcessor {
  write(audio: ArrayBuffer): Promise<void>;
  writeFloat(samples: Float32Array): Promise<void>;
  requestFinish?(): void;
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
  private queuedTasks: number = 0;
  private maxQueuedTasks: number = 0;
  private nativeCallsInFlight: number = 0;
  private observeState: boolean = false;

  constructor(processor: SessionAudioProcessor, onError: (message: string) => void,
    observeState: boolean = false) {
    this.processor = processor;
    this.onError = onError;
    this.observeState = observeState;
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
    try {
      // The core uses this synchronous intent only while a customer callback is on the stack. It
      // restores endpoint-final promotion without running native stop ahead of queued PCM.
      this.processor.requestFinish?.();
    } catch (e) {
      this.fail(`${e}`);
    }
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

  /** Read-only counters consumed by diagnostics; they never gate dispatch behavior. */
  diagnosticState(): Record<string, Object> {
    const state: Record<string, Object> = {};
    state['audioQueueDepth'] = this.queuedTasks;
    state['maxAudioQueueDepth'] = this.maxQueuedTasks;
    state['nativeCallsInFlight'] = this.nativeCallsInFlight;
    state['accepting'] = this.accepting;
    state['canceled'] = this.canceled;
    state['failed'] = this.failed;
    return state;
  }

  private enqueue(task: () => Promise<void>): void {
    if (this.observeState) {
      this.queuedTasks += 1;
      this.maxQueuedTasks = Math.max(this.maxQueuedTasks, this.queuedTasks);
    }
    const sessionPredecessor = this.pending;
    const execution = SessionAudioDispatcher.executionTail.then(async (): Promise<void> => {
      await sessionPredecessor;
      if (this.observeState) this.nativeCallsInFlight += 1;
      try {
        await task();
      } finally {
        if (this.observeState) {
          this.nativeCallsInFlight -= 1;
          this.queuedTasks = Math.max(0, this.queuedTasks - 1);
        }
      }
    });
    this.pending = execution;
    SessionAudioDispatcher.executionTail = execution.catch((): void => {});
  }

  private fail(message: string): void {
    if (this.failed || this.canceled) return;
    this.failed = true;
    this.accepting = false;
    try {
      this.onError(message);
    } catch (_e) {
      // A consumer callback must not reject the shared native execution queue.
    }
  }
}
