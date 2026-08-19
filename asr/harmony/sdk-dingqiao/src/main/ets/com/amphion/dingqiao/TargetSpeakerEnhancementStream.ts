export const TARGET_SPEAKER_CHUNK_SAMPLES: number = 32000;
export const TARGET_SPEAKER_OVERLAP_SAMPLES: number = 4000;
export const TARGET_SPEAKER_HOP_SAMPLES: number =
  TARGET_SPEAKER_CHUNK_SAMPLES - TARGET_SPEAKER_OVERLAP_SAMPLES;

export interface TargetSpeakerEnhancementChunk {
  startSample: number;
  availableSamples: number;
  isFinal: boolean;
  samples: Float32Array;
}

/**
 * Converts arbitrarily framed 16 kHz PCM into the fixed 2 s / 0.25 s-overlap
 * input expected by the target-speaker enhancement model.
 */
export class TargetSpeakerEnhancementInput {
  private buffered: Float32Array = new Float32Array(0);
  private bufferStartSample: number = 0;
  private totalSamples: number = 0;
  private nextChunkStartSample: number = 0;
  private finished: boolean = false;

  append(samples: Float32Array): TargetSpeakerEnhancementChunk[] {
    if (this.finished) throw new Error('target speaker enhancement input is finished');
    if (samples.length === 0) return [];
    const merged = new Float32Array(this.buffered.length + samples.length);
    merged.set(this.buffered, 0);
    merged.set(samples, this.buffered.length);
    this.buffered = merged;
    this.totalSamples += samples.length;

    const chunks: TargetSpeakerEnhancementChunk[] = [];
    while (this.totalSamples - this.nextChunkStartSample >= TARGET_SPEAKER_CHUNK_SAMPLES) {
      chunks.push(this.makeChunk(this.nextChunkStartSample, TARGET_SPEAKER_CHUNK_SAMPLES, false));
      this.nextChunkStartSample += TARGET_SPEAKER_HOP_SAMPLES;
    }
    this.compact();
    return chunks;
  }

  finish(): TargetSpeakerEnhancementChunk[] {
    if (this.finished) return [];
    this.finished = true;
    const chunks: TargetSpeakerEnhancementChunk[] = [];
    while (this.nextChunkStartSample < this.totalSamples) {
      const available = Math.min(
        TARGET_SPEAKER_CHUNK_SAMPLES,
        this.totalSamples - this.nextChunkStartSample,
      );
      const nextStart = this.nextChunkStartSample + TARGET_SPEAKER_HOP_SAMPLES;
      chunks.push(this.makeChunk(
        this.nextChunkStartSample,
        available,
        nextStart >= this.totalSamples,
      ));
      this.nextChunkStartSample = nextStart;
    }
    this.compact();
    return chunks;
  }

  retainedBytes(): number { return this.buffered.byteLength; }

  private makeChunk(startSample: number, availableSamples: number,
    isFinal: boolean): TargetSpeakerEnhancementChunk {
    const offset = startSample - this.bufferStartSample;
    if (offset < 0 || offset + availableSamples > this.buffered.length) {
      throw new Error('target speaker enhancement input buffer is inconsistent');
    }
    const chunk = new Float32Array(TARGET_SPEAKER_CHUNK_SAMPLES);
    chunk.set(this.buffered.slice(offset, offset + availableSamples), 0);
    return {
      startSample,
      availableSamples,
      isFinal,
      samples: chunk,
    };
  }

  private compact(): void {
    const discard = Math.min(
      this.buffered.length,
      Math.max(0, this.nextChunkStartSample - this.bufferStartSample),
    );
    if (discard === 0) return;
    this.buffered = this.buffered.slice(discard);
    this.bufferStartSample += discard;
  }
}

/** Reconstructs one continuous PCM stream from consecutively enhanced chunks. */
export class TargetSpeakerEnhancementStitcher {
  private previousTail?: Float32Array;
  private firstChunk: boolean = true;

  append(chunk: TargetSpeakerEnhancementChunk, enhanced: Float32Array): Float32Array {
    if (enhanced.length !== TARGET_SPEAKER_CHUNK_SAMPLES) {
      throw new Error(`enhanced chunk must contain ${TARGET_SPEAKER_CHUNK_SAMPLES} samples`);
    }
    if (this.firstChunk) {
      this.firstChunk = false;
      if (chunk.isFinal) return enhanced.slice(0, chunk.availableSamples);
      this.previousTail = enhanced.slice(TARGET_SPEAKER_HOP_SAMPLES);
      return enhanced.slice(0, TARGET_SPEAKER_HOP_SAMPLES);
    }

    const outputSamples = chunk.isFinal ? chunk.availableSamples : TARGET_SPEAKER_HOP_SAMPLES;
    const output = new Float32Array(outputSamples);
    const blendSamples = Math.min(TARGET_SPEAKER_OVERLAP_SAMPLES, outputSamples);
    const previous = this.previousTail;
    if (previous === undefined) throw new Error('target speaker enhancement tail is missing');
    for (let i = 0; i < blendSamples; i++) {
      const position = TARGET_SPEAKER_OVERLAP_SAMPLES <= 1 ? 1.0 :
        i / (TARGET_SPEAKER_OVERLAP_SAMPLES - 1);
      const weight = (1.0 - Math.cos(Math.PI * position)) / 2.0;
      output[i] = previous[i] * (1.0 - weight) + enhanced[i] * weight;
    }
    if (outputSamples > blendSamples) {
      output.set(enhanced.slice(blendSamples, outputSamples), blendSamples);
    }
    this.previousTail = chunk.isFinal ? undefined :
      enhanced.slice(TARGET_SPEAKER_HOP_SAMPLES);
    return output;
  }
}

export interface TargetSpeakerEnhancementProcessor {
  process(chunk: TargetSpeakerEnhancementChunk): Promise<Float32Array>;
}

export interface TargetSpeakerEnhancementObserver {
  onOutput(samples: Float32Array): Promise<void> | void;
  onFinished(): void;
  onError(message: string): void;
  onMetrics?(processingMs: number, queuedChunks: number, maxQueuedChunks: number): void;
}

export class TargetSpeakerEnhancementQueueStats {
  submittedBytes: number = 0;
  processedBytes: number = 0;
  queuedBytes: number = 0;
  queuedChunks: number = 0;
  maxQueuedChunks: number = 0;
  retainedBytes: number = 0;
  highWaterBytes: number = 0;
  lowWaterBytes: number = 0;
  accepting: boolean = false;
}

/**
 * A single-flight queue around the native front end. Serial execution bounds
 * memory and preserves caller audio order even though inference is async.
 */
export class TargetSpeakerEnhancementPipeline {
  private input: TargetSpeakerEnhancementInput = new TargetSpeakerEnhancementInput();
  private stitcher: TargetSpeakerEnhancementStitcher = new TargetSpeakerEnhancementStitcher();
  private processor: TargetSpeakerEnhancementProcessor;
  private observer: TargetSpeakerEnhancementObserver;
  private pending: Promise<void> = Promise.resolve();
  private finishTask?: Promise<void>;
  private accepting: boolean = true;
  private canceled: boolean = false;
  private failed: boolean = false;
  private queuedChunks: number = 0;
  private maxQueuedChunks: number = 0;
  private submittedBytes: number = 0;
  private processedBytes: number = 0;
  private highWaterBytes: number;
  private lowWaterBytes: number;
  private queue: (TargetSpeakerEnhancementChunk | undefined)[] = [];
  private queueHead: number = 0;
  private retainedBytes: number = 0;
  private pumpTask?: Promise<void>;
  private capacityWaiters: ((accepted: boolean) => void)[] = [];

  constructor(processor: TargetSpeakerEnhancementProcessor, observer: TargetSpeakerEnhancementObserver,
    highWaterBytes: number = 512 * 1024, lowWaterBytes: number = 256 * 1024) {
    if (highWaterBytes <= 0 || lowWaterBytes < 0 || lowWaterBytes > highWaterBytes) {
      throw new Error('target speaker enhancement water marks must satisfy 0 <= low <= high');
    }
    this.processor = processor;
    this.observer = observer;
    // A smaller watermark would block before the first 2-second model chunk exists.
    this.highWaterBytes = Math.max(highWaterBytes, TARGET_SPEAKER_CHUNK_SAMPLES * 2);
    this.lowWaterBytes = Math.min(lowWaterBytes, this.highWaterBytes);
  }

  append(samples: Float32Array): void {
    if (!this.accepting) throw new Error('target speaker enhancement pipeline is not accepting audio');
    this.submittedBytes += samples.length * 2;
    this.enqueue(this.input.append(samples));
  }

  appendAsync(samples: Float32Array): Promise<boolean> {
    this.append(samples);
    return this.whenWritable();
  }

  whenWritable(): Promise<boolean> {
    if (this.canceled || this.failed) return Promise.resolve(false);
    if (this.queuedPcmBytes() <= this.highWaterBytes) return Promise.resolve(true);
    return new Promise<boolean>((resolve: (accepted: boolean) => void): void => {
      this.capacityWaiters.push(resolve);
    });
  }

  queueStats(): TargetSpeakerEnhancementQueueStats {
    const result = new TargetSpeakerEnhancementQueueStats();
    result.submittedBytes = this.submittedBytes;
    result.processedBytes = this.processedBytes;
    result.queuedBytes = this.queuedPcmBytes();
    result.queuedChunks = this.queuedChunks;
    result.maxQueuedChunks = this.maxQueuedChunks;
    result.retainedBytes = this.retainedBytes + this.input.retainedBytes();
    result.highWaterBytes = this.highWaterBytes;
    result.lowWaterBytes = this.lowWaterBytes;
    result.accepting = this.accepting && !this.canceled && !this.failed;
    return result;
  }

  finish(): Promise<void> {
    if (this.finishTask !== undefined) return this.finishTask;
    if (this.canceled) return Promise.resolve();
    this.accepting = false;
    this.enqueue(this.input.finish());
    this.finishTask = this.waitUntilDrained().then((): void => {
      if (!this.canceled && !this.failed) this.observer.onFinished();
    });
    return this.finishTask;
  }

  cancel(): void {
    if (this.canceled) return;
    this.accepting = false;
    this.canceled = true;
    this.dropPendingChunks();
    this.resolveCapacityWaiters(false);
  }

  private enqueue(chunks: TargetSpeakerEnhancementChunk[]): void {
    for (let i = 0; i < chunks.length; i++) {
      const chunk = chunks[i];
      this.queuedChunks += 1;
      this.maxQueuedChunks = Math.max(this.maxQueuedChunks, this.queuedChunks);
      this.retainedBytes += chunk.samples.byteLength;
      this.queue.push(chunk);
    }
    this.ensurePump();
  }

  private whenIdle(): Promise<void> {
    return this.pending;
  }

  private async waitUntilDrained(): Promise<void> {
    while (this.pumpTask !== undefined || this.queueHead < this.queue.length) {
      await this.whenIdle();
      await Promise.resolve();
    }
  }

  private ensurePump(): void {
    if (this.pumpTask !== undefined || this.canceled || this.failed || this.queueHead >= this.queue.length) return;
    let resolveIdle: (() => void) | undefined;
    this.pending = new Promise<void>((resolve: () => void): void => { resolveIdle = resolve; });
    const execution = this.drainQueue();
    this.pumpTask = execution;
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
      const chunk = this.queue[this.queueHead];
      this.queue[this.queueHead] = undefined;
      this.queueHead += 1;
      if (chunk === undefined) continue;
      const startedAt = Date.now();
      try {
        const enhanced = await this.processor.process(chunk);
        if (this.canceled || this.failed) return;
        const output = this.stitcher.append(chunk, enhanced);
        if (output.length > 0) await this.observer.onOutput(output);
        this.processedBytes += output.length * 2;
      } catch (e) {
        this.fail(`${e}`);
      } finally {
        this.queuedChunks = Math.max(0, this.queuedChunks - 1);
        this.retainedBytes = Math.max(0, this.retainedBytes - chunk.samples.byteLength);
        if (this.queuedPcmBytes() <= this.lowWaterBytes) this.resolveCapacityWaiters(true);
        this.observer.onMetrics?.(
          Date.now() - startedAt,
          this.queuedChunks,
          this.maxQueuedChunks
        );
        this.compactQueueIfNeeded();
      }
    }
    if (this.canceled || this.failed) this.dropPendingChunks();
    if (this.queueHead >= this.queue.length) {
      this.queue = [];
      this.queueHead = 0;
    }
  }

  private queuedPcmBytes(): number {
    return Math.max(0, this.submittedBytes - this.processedBytes);
  }

  private compactQueueIfNeeded(): void {
    if (this.queueHead < 64 || this.queueHead * 2 < this.queue.length) return;
    this.queue = this.queue.slice(this.queueHead);
    this.queueHead = 0;
  }

  private dropPendingChunks(): void {
    while (this.queueHead < this.queue.length) {
      const chunk = this.queue[this.queueHead];
      this.queue[this.queueHead] = undefined;
      this.queueHead += 1;
      if (chunk === undefined) continue;
      this.queuedChunks = Math.max(0, this.queuedChunks - 1);
      this.retainedBytes = Math.max(0, this.retainedBytes - chunk.samples.byteLength);
    }
    this.queue = [];
    this.queueHead = 0;
  }

  private resolveCapacityWaiters(accepted: boolean): void {
    const waiters = this.capacityWaiters;
    this.capacityWaiters = [];
    for (let i = 0; i < waiters.length; i++) waiters[i](accepted);
  }

  private fail(message: string): void {
    if (this.failed || this.canceled) return;
    this.failed = true;
    this.accepting = false;
    this.dropPendingChunks();
    this.resolveCapacityWaiters(false);
    this.observer.onError(message);
  }
}
