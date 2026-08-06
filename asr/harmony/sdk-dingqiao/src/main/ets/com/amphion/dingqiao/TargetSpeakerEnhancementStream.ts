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
  onOutput(samples: Float32Array): void;
  onFinished(): void;
  onError(message: string): void;
  onMetrics?(processingMs: number, queuedChunks: number, maxQueuedChunks: number): void;
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
  private acceptedSamples: number = 0;

  constructor(processor: TargetSpeakerEnhancementProcessor, observer: TargetSpeakerEnhancementObserver) {
    this.processor = processor;
    this.observer = observer;
  }

  append(samples: Float32Array): void {
    if (!this.accepting) throw new Error('target speaker enhancement pipeline is not accepting audio');
    this.enqueue(this.input.append(samples));
    this.acceptedSamples += samples.length;
  }

  inputSamplesAccepted(): number { return this.acceptedSamples; }

  finish(): Promise<void> {
    if (this.finishTask !== undefined) return this.finishTask;
    if (this.canceled) return Promise.resolve();
    this.accepting = false;
    this.enqueue(this.input.finish());
    this.finishTask = this.pending.then((): void => {
      if (!this.canceled && !this.failed) this.observer.onFinished();
    });
    return this.finishTask;
  }

  cancel(): void {
    if (this.canceled) return;
    this.accepting = false;
    this.canceled = true;
  }

  private enqueue(chunks: TargetSpeakerEnhancementChunk[]): void {
    for (let i = 0; i < chunks.length; i++) {
      const chunk = chunks[i];
      this.queuedChunks += 1;
      this.maxQueuedChunks = Math.max(this.maxQueuedChunks, this.queuedChunks);
      this.pending = this.pending.then(async (): Promise<void> => {
        if (this.canceled || this.failed) {
          this.queuedChunks -= 1;
          return;
        }
        const startedAt = Date.now();
        try {
          const enhanced = await this.processor.process(chunk);
          if (this.canceled || this.failed) return;
          const output = this.stitcher.append(chunk, enhanced);
          if (output.length > 0) this.observer.onOutput(output);
        } catch (e) {
          if (this.canceled || this.failed) return;
          this.failed = true;
          this.observer.onError(`${e}`);
        } finally {
          this.queuedChunks -= 1;
          this.observer.onMetrics?.(
            Date.now() - startedAt,
            this.queuedChunks,
            this.maxQueuedChunks
          );
        }
      });
    }
  }
}
