import { fileIo } from '@kit.CoreFileKit';
import {
  OnlineStream,
  readWaveFromBinary,
  Samples,
  SpeakerEmbeddingExtractor,
  SpeakerEmbeddingExtractorConfig
} from 'sherpa_onnx';

export class SpeakerEnroller {
  private modelPath: string;
  private extractor: SpeakerEmbeddingExtractor;
  private context?: Context;

  constructor(modelPath: string, numThreads: number = 1, context?: Context, extractor?: SpeakerEmbeddingExtractor) {
    if (modelPath.trim().length === 0) throw new Error('SpeakerEnroller modelPath must not be blank');
    this.modelPath = modelPath;
    this.context = context;
    if (extractor !== undefined) {
      // Reuse a pooled extractor (shared with the recognition path) so the ~38 MB model loads once.
      this.extractor = extractor;
    } else {
      const config = new SpeakerEmbeddingExtractorConfig();
      config.model = modelPath;
      config.numThreads = numThreads;
      config.debug = false;
      // rawfile 加载器只能吃 rawfile 相对路径;把 resourceManager 传给一个绝对路径会让 native 端
      // 按 rawfile 找不到而 abort(与 Runtime.getOrCreateSpeakerExtractor 同一守卫,也与下方 readWaveSamples 一致)。
      const rm = modelPath.startsWith('/') ? undefined : context?.resourceManager;
      this.extractor = new SpeakerEmbeddingExtractor(config, rm);
    }
  }

  get embeddingDim(): number {
    return this.extractor.dim;
  }

  enroll(segments: Float32Array[], sampleRate: number = 16000): Float32Array {
    if (segments.length === 0) throw new Error('enroll() needs at least 1 segment');
    if (sampleRate !== 16000) throw new Error('SpeakerEnroller only supports 16 kHz PCM');
    const embeddings: Float32Array[] = [];
    for (let i = 0; i < segments.length; i++) {
      if (segments[i].length === 0) continue;
      embeddings.push(this.computeEmbedding(segments[i], sampleRate));
    }
    if (embeddings.length === 0) throw new Error('all enrollment segments are empty');
    return meanNormalize(embeddings, this.extractor.dim);
  }

  enrollFiles(audioPaths: string[]): Float32Array {
    if (audioPaths.length === 0) throw new Error('enrollFiles() needs at least 1 audio path');
    const segments: Float32Array[] = [];
    for (let i = 0; i < audioPaths.length; i++) {
      segments.push(this.readWaveSamples(audioPaths[i]));
    }
    return this.enroll(segments, 16000);
  }

  close(): void {
    // sherpa_onnx Harmony binding does not expose an explicit extractor release API yet.
  }

  private computeEmbedding(samples: Float32Array, sampleRate: number): Float32Array {
    const stream: OnlineStream = this.extractor.createStream();
    try {
      const wave: Samples = { samples: samples, sampleRate: sampleRate } as Samples;
      stream.acceptWaveform(wave);
      return this.extractor.compute(stream);
    } finally {
      stream.close();
    }
  }

  private readWaveSamples(path: string): Float32Array {
    if (this.context !== undefined && !path.startsWith('/')) {
      const rawData: Uint8Array = this.context.resourceManager.getRawFileContentSync(path);
      const rawWave = readWaveFromBinary(rawData) as Samples;
      if (rawWave.sampleRate !== 16000) throw new Error(`voiceprint sample ${path} must be 16 kHz`);
      return rawWave.samples;
    }
    const fp = fileIo.openSync(path);
    try {
      const stat = fileIo.statSync(fp.fd);
      const buffer = new ArrayBuffer(stat.size);
      fileIo.readSync(fp.fd, buffer);
      const wave = readWaveFromBinary(new Uint8Array(buffer)) as Samples;
      if (wave.sampleRate !== 16000) throw new Error(`voiceprint sample ${path} must be 16 kHz`);
      return wave.samples;
    } finally {
      fileIo.closeSync(fp);
    }
  }
}

function meanNormalize(embeddings: Float32Array[], dim: number): Float32Array {
  const out = new Float32Array(dim);
  for (let i = 0; i < embeddings.length; i++) {
    const embedding = embeddings[i];
    for (let j = 0; j < Math.min(dim, embedding.length); j++) {
      out[j] += embedding[j];
    }
  }
  for (let j = 0; j < dim; j++) out[j] /= embeddings.length;
  let norm = 0;
  for (let j = 0; j < dim; j++) norm += out[j] * out[j];
  norm = Math.sqrt(norm);
  if (norm > 0) {
    for (let j = 0; j < dim; j++) out[j] /= norm;
  }
  return out;
}
