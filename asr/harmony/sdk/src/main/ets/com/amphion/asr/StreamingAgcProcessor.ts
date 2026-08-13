export interface AgcBackend {
  process(frame: Float32Array): Float32Array;
  close(): void;
}

export type AgcBackendFactory = () => AgcBackend;

export class ProcessedAudioFrame {
  raw: Float32Array;
  processed: Float32Array;

  constructor(raw: Float32Array, processed: Float32Array) {
    this.raw = raw;
    this.processed = processed;
  }
}

/** Reframes arbitrary caller chunks into the 10 ms mono frames required by WebRTC AGC2. */
export class StreamingAgcProcessor {
  private frameSamples: number;
  private backendFactory: AgcBackendFactory;
  private backend?: AgcBackend;
  private carry: Float32Array = new Float32Array(0);
  private closed: boolean = false;

  constructor(sampleRate: number, backendFactory: AgcBackendFactory) {
    if (sampleRate <= 0 || sampleRate % 100 !== 0) {
      throw new Error(`sampleRate must have an integral 10ms frame, got ${sampleRate}`);
    }
    this.frameSamples = sampleRate / 100;
    this.backendFactory = backendFactory;
  }

  process(samples: Float32Array): ProcessedAudioFrame[] {
    if (this.closed) throw new Error('AGC processor is closed');
    if (samples.length === 0) return [];
    const merged = concat(this.carry, samples);
    const completeSamples = Math.floor(merged.length / this.frameSamples) * this.frameSamples;
    if (completeSamples === 0) {
      this.carry = merged.slice();
      return [];
    }
    const rawOutput = new Float32Array(completeSamples);
    const processedOutput = new Float32Array(completeSamples);
    let offset = 0;
    while (offset < completeSamples) {
      const raw = merged.slice(offset, offset + this.frameSamples);
      const frame = this.processFrame(raw);
      rawOutput.set(frame.raw, offset);
      processedOutput.set(frame.processed, offset);
      offset += this.frameSamples;
    }
    this.carry = offset < merged.length ? merged.slice(offset) : new Float32Array(0);
    // AGC still runs on strict 10 ms frames, but preserve the caller's decoder submission
    // granularity. Decoding every internal frame separately halves burst throughput because the
    // Harmony adapter awaits each native decode on its serial audio dispatcher.
    return [new ProcessedAudioFrame(rawOutput, processedOutput)];
  }

  flush(): ProcessedAudioFrame[] {
    if (this.closed) throw new Error('AGC processor is closed');
    if (this.carry.length === 0) return [];

    const raw = this.carry;
    this.carry = new Float32Array(0);
    const padded = new Float32Array(this.frameSamples);
    padded.set(raw);
    const processed = this.processFrame(padded).processed.slice(0, raw.length);
    return [new ProcessedAudioFrame(raw, processed)];
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.carry = new Float32Array(0);
    this.backend?.close();
    this.backend = undefined;
  }

  private processFrame(raw: Float32Array): ProcessedAudioFrame {
    if (this.backend === undefined) this.backend = this.backendFactory();
    const processed = this.backend.process(raw);
    if (processed.length !== raw.length) {
      throw new Error(`AGC backend changed frame size: ${raw.length} -> ${processed.length}`);
    }
    return new ProcessedAudioFrame(raw, processed);
  }
}

function concat(left: Float32Array, right: Float32Array): Float32Array {
  if (left.length === 0) return right;
  const output = new Float32Array(left.length + right.length);
  output.set(left, 0);
  output.set(right, left.length);
  return output;
}
