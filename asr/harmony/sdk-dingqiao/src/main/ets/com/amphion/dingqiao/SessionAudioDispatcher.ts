export interface SessionAudioProcessor {
  write(audio: ArrayBuffer): Promise<void>;
  writeFloat(samples: Float32Array): Promise<void>;
  requestFinish?(): void;
  finish(): Promise<void>;
}

const TASK_BYTES: number = 1;
const TASK_FLOAT: number = 2;
const TASK_FINISH: number = 3;
const DEFAULT_HIGH_WATER_BYTES: number = 2 * 1024 * 1024;
const DEFAULT_LOW_WATER_BYTES: number = 1 * 1024 * 1024;

class SessionAudioDispatchItem {
  kind: number;
  audio?: ArrayBuffer;
  samples?: Float32Array;
  byteLength: number;

  constructor(kind: number, byteLength: number) {
    this.kind = kind;
    this.byteLength = byteLength;
  }
}

export class SessionAudioQueueStats {
  queuedBytes: number = 0;
  queuedChunks: number = 0;
  highWaterBytes: number = 0;
  lowWaterBytes: number = 0;
  scheduledPumps: number = 0;
  accepting: boolean = false;
}

/**
 * Serializes public audio submissions without running recognition work in the
 * caller's writeAudio stack. Frames are snapshotted before returning because
 * microphone integrations commonly reuse their capture buffers.
 *
 * A burst owns one drain pump, not one chained Promise per PCM frame. The
 * compatibility write() remains non-blocking; offline callers should use
 * writeWithBackpressure() so retained PCM stays near the configured high-water
 * mark while decoding still runs as fast as the device can consume it.
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
  private queue: SessionAudioDispatchItem[] = [];
  private queueHead: number = 0;
  private queuedBytes: number = 0;
  private queuedChunks: number = 0;
  private pumpTask?: Promise<void>;
  private scheduledPumps: number = 0;
  private capacityWaiters: ((accepted: boolean) => void)[] = [];
  private highWaterBytes: number;
  private lowWaterBytes: number;

  constructor(processor: SessionAudioProcessor, onError: (message: string) => void,
    highWaterBytes: number = DEFAULT_HIGH_WATER_BYTES,
    lowWaterBytes: number = DEFAULT_LOW_WATER_BYTES) {
    if (highWaterBytes <= 0 || lowWaterBytes < 0 || lowWaterBytes > highWaterBytes) {
      throw new Error('audio queue water marks must satisfy 0 <= low <= high');
    }
    this.processor = processor;
    this.onError = onError;
    this.highWaterBytes = highWaterBytes;
    this.lowWaterBytes = lowWaterBytes;
  }

  write(audio: ArrayBuffer): boolean {
    if (!this.accepting || this.canceled || this.failed || audio.byteLength === 0) return false;
    const item = new SessionAudioDispatchItem(TASK_BYTES, audio.byteLength);
    item.audio = audio.slice(0);
    this.enqueue(item);
    return true;
  }

  writeWithBackpressure(audio: ArrayBuffer): Promise<boolean> {
    if (!this.write(audio)) return Promise.resolve(false);
    return this.waitForCapacity();
  }

  writeFloat(samples: Float32Array): boolean {
    if (!this.accepting || this.canceled || this.failed || samples.length === 0) return false;
    const snapshot = samples.slice();
    const item = new SessionAudioDispatchItem(TASK_FLOAT, snapshot.byteLength);
    item.samples = snapshot;
    this.enqueue(item);
    return true;
  }

  writeFloatWithBackpressure(samples: Float32Array): Promise<boolean> {
    if (!this.writeFloat(samples)) return Promise.resolve(false);
    return this.waitForCapacity();
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
    this.enqueue(new SessionAudioDispatchItem(TASK_FINISH, 0));
    this.finishTask = this.pending;
    return this.finishTask;
  }

  cancel(): void {
    this.accepting = false;
    this.canceled = true;
    this.dropPendingItems();
    this.resolveCapacityWaiters(false);
  }

  whenIdle(): Promise<void> {
    return this.pending;
  }

  whenWritable(): Promise<boolean> {
    return this.waitForCapacity();
  }

  queueStats(): SessionAudioQueueStats {
    const result = new SessionAudioQueueStats();
    result.queuedBytes = this.queuedBytes;
    result.queuedChunks = this.queuedChunks;
    result.highWaterBytes = this.highWaterBytes;
    result.lowWaterBytes = this.lowWaterBytes;
    result.scheduledPumps = this.scheduledPumps;
    result.accepting = this.accepting && !this.canceled && !this.failed;
    return result;
  }

  private waitForCapacity(): Promise<boolean> {
    if (this.canceled || this.failed) return Promise.resolve(false);
    if (this.queuedBytes <= this.highWaterBytes) return Promise.resolve(true);
    return new Promise<boolean>((resolve: (accepted: boolean) => void): void => {
      this.capacityWaiters.push(resolve);
    });
  }

  private enqueue(item: SessionAudioDispatchItem): void {
    if (this.canceled || this.failed) return;
    this.queue.push(item);
    if (item.byteLength > 0) {
      this.queuedBytes += item.byteLength;
      this.queuedChunks += 1;
    }
    this.ensurePump();
  }

  private ensurePump(): void {
    if (this.pumpTask !== undefined || this.canceled || this.failed) return;
    this.scheduledPumps += 1;
    let resolveIdle: (() => void) | undefined;
    this.pending = new Promise<void>((resolve: () => void): void => { resolveIdle = resolve; });
    const execution = SessionAudioDispatcher.executionTail.then(async (): Promise<void> => {
      await this.drainQueue();
    });
    this.pumpTask = execution;
    SessionAudioDispatcher.executionTail = execution.catch((): void => {});
    execution.then((): void => {
      this.pumpTask = undefined;
      resolveIdle?.();
      if (this.queueHead < this.queue.length && !this.canceled && !this.failed) this.ensurePump();
    }).catch((e: Object): void => {
      this.pumpTask = undefined;
      this.fail(`${e}`);
      resolveIdle?.();
    });
  }

  private async drainQueue(): Promise<void> {
    while (this.queueHead < this.queue.length && !this.canceled && !this.failed) {
      const item = this.queue[this.queueHead];
      this.queueHead += 1;
      try {
        if (item.kind === TASK_BYTES && item.audio !== undefined) {
          await this.processor.write(item.audio);
        } else if (item.kind === TASK_FLOAT && item.samples !== undefined) {
          await this.processor.writeFloat(item.samples);
        } else if (item.kind === TASK_FINISH) {
          await this.processor.finish();
        }
      } catch (e) {
        this.fail(`${e}`);
      } finally {
        this.releaseItem(item);
      }
    }
    if (this.canceled || this.failed) this.dropPendingItems();
    if (this.queueHead >= this.queue.length) {
      this.queue = [];
      this.queueHead = 0;
    }
  }

  private releaseItem(item: SessionAudioDispatchItem): void {
    if (item.byteLength <= 0) return;
    this.queuedBytes = Math.max(0, this.queuedBytes - item.byteLength);
    this.queuedChunks = Math.max(0, this.queuedChunks - 1);
    if (this.queuedBytes <= this.lowWaterBytes) this.resolveCapacityWaiters(true);
  }

  private dropPendingItems(): void {
    while (this.queueHead < this.queue.length) {
      const item = this.queue[this.queueHead];
      this.queueHead += 1;
      this.releaseItem(item);
    }
    if (this.queueHead >= this.queue.length) {
      this.queue = [];
      this.queueHead = 0;
    }
  }

  private resolveCapacityWaiters(accepted: boolean): void {
    if (this.capacityWaiters.length === 0) return;
    const waiters = this.capacityWaiters;
    this.capacityWaiters = [];
    for (let index = 0; index < waiters.length; index++) {
      try {
        waiters[index](accepted);
      } catch (_e) {
      }
    }
  }

  private fail(message: string): void {
    if (this.failed || this.canceled) return;
    this.failed = true;
    this.accepting = false;
    this.dropPendingItems();
    this.resolveCapacityWaiters(false);
    try {
      this.onError(message);
    } catch (_e) {
      // A consumer callback must not reject the shared native execution queue.
    }
  }
}
