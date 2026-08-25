import { ProcessedAudioFrame } from './StreamingAgcProcessor';

export interface AgcFrameProcessor {
  process(samples: Float32Array): ProcessedAudioFrame[];
  flush(): ProcessedAudioFrame[];
  close(): void;
}

export type AgcFrameConsumer = (frame: ProcessedAudioFrame) => void;
export type AsyncAgcFrameConsumer = (frame: ProcessedAudioFrame) => Promise<void>;

/** Delivers every paired AGC frame once, in order, through both sync and async session lanes. */
export class StreamingAgcIngress {
  private processor: AgcFrameProcessor;
  private closed: boolean = false;

  constructor(processor: AgcFrameProcessor) {
    this.processor = processor;
  }

  accept(samples: Float32Array, consume: AgcFrameConsumer): void {
    if (this.closed) throw new Error('AGC ingress is closed');
    const frames = this.processor.process(samples);
    for (let index = 0; index < frames.length; index++) consume(frames[index]);
  }

  async acceptAsync(samples: Float32Array, consume: AsyncAgcFrameConsumer): Promise<void> {
    if (this.closed) throw new Error('AGC ingress is closed');
    const frames = this.processor.process(samples);
    for (let index = 0; index < frames.length; index++) await consume(frames[index]);
  }

  flush(consume: AgcFrameConsumer): void {
    if (this.closed) throw new Error('AGC ingress is closed');
    const frames = this.processor.flush();
    for (let index = 0; index < frames.length; index++) consume(frames[index]);
  }

  async flushAsync(consume: AsyncAgcFrameConsumer): Promise<void> {
    if (this.closed) throw new Error('AGC ingress is closed');
    const frames = this.processor.flush();
    for (let index = 0; index < frames.length; index++) await consume(frames[index]);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.processor.close();
  }
}
