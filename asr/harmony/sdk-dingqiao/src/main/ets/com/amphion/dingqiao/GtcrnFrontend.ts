export interface GtcrnOutput { samples: Float32Array; durationMs: number; }
export interface GtcrnProcessor {
  process(samples: Float32Array, flush: boolean): Promise<GtcrnOutput>;
}

/** Length-preserving PCM boundary shared by ASR and diarization. No per-chunk normalization. */
export class GtcrnFrontend {
  inputSamples: number = 0;
  outputSamples: number = 0;
  processingMs: number = 0;
  private ended: boolean = false;
  private processor: GtcrnProcessor;
  constructor(processor: GtcrnProcessor) { this.processor = processor; }

  async run(audio: ArrayBuffer): Promise<ArrayBuffer> {
    if (this.ended) throw new Error('GTCRN input after flush');
    if (audio.byteLength % 2 !== 0) throw new Error('GTCRN requires PCM16');
    const pcm = new DataView(audio);
    const samples = new Float32Array(audio.byteLength / 2);
    for (let i = 0; i < samples.length; i++) samples[i] = pcm.getInt16(i * 2, true) / 32768;
    this.inputSamples += samples.length;
    return this.convert(await this.processor.process(samples, false));
  }

  async flush(): Promise<ArrayBuffer> {
    if (this.ended) return new ArrayBuffer(0);
    this.ended = true;
    const result = this.convert(await this.processor.process(new Float32Array(0), true));
    if (this.outputSamples !== this.inputSamples) {
      throw new Error(`GTCRN length mismatch: input=${this.inputSamples}, output=${this.outputSamples}`);
    }
    return result;
  }

  private convert(result: GtcrnOutput): ArrayBuffer {
    const pcm = new ArrayBuffer(result.samples.length * 2);
    const view = new DataView(pcm);
    for (let i = 0; i < result.samples.length; i++) {
      const sample = result.samples[i];
      if (!Number.isFinite(sample)) throw new Error('GTCRN nonfinite sample');
      view.setInt16(i * 2, Math.max(-32768, Math.min(32767, Math.round(sample * 32768))), true);
    }
    this.outputSamples += result.samples.length;
    this.processingMs += result.durationMs;
    if (this.outputSamples > this.inputSamples) throw new Error('GTCRN output exceeds input');
    return pcm;
  }
}
