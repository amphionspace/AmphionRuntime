import { fileIo } from '@kit.CoreFileKit';
import {
  OnlineStream,
  readWaveFromBinary,
  Samples,
  SpeakerEmbeddingExtractor,
  SpeakerEmbeddingExtractorConfig
} from 'sherpa_onnx';

const SPEAKER_SAMPLE_RATE_HZ: number = 16000;
/**
 * 分段模板的窗长/步长（缺陷 #97 第二轮）。整文件模板对 8 s 朗读建模，与 1 s 左右的 PTT 短指令
 * 不在一个尺度上：客户「OKOK」对 near/mid/far 整文件模板只有 0.245/0.269/0.370，刚擦过 0.35。
 * 把每份注册样本再按 2 s 窗、1 s 步切成分段模板后，同一段 OKOK 的最大相似度 0.370 → 0.444，
 * 机主 1 s 窗口低于 0.35 的比例 13.8% → 10.6%。短对短匹配同样会抬高非机主短窗（1 s 最高
 * 0.31 → 0.39、1.5 s 最高 0.20 → 0.33），所以分段模板只用于 final 打分，流式确认与边界校验
 * 仍用整文件模板——非机主要被"确认"的门槛不变，未确认的 final 仍要过 0.45 下沿。
 */
export const SEGMENT_TEMPLATE_SECONDS: number = 2.0;
export const SEGMENT_TEMPLATE_HOP_SECONDS: number = 1.0;
const SEGMENT_TEMPLATE_MIN_RMS: number = 0.0178; // 约 -35 dBFS，跳过静音块

export class SpeakerEnroller {
  private modelPath: string;
  private extractor: SpeakerEmbeddingExtractor;
  private context?: Context;
  private ownsExtractor: boolean;
  private closed: boolean = false;

  constructor(modelPath: string, numThreads: number = 1, context?: Context, extractor?: SpeakerEmbeddingExtractor) {
    if (modelPath.trim().length === 0) throw new Error('SpeakerEnroller modelPath must not be blank');
    this.modelPath = modelPath;
    this.context = context;
    if (extractor !== undefined) {
      // Reuse a pooled extractor (shared with the recognition path) so the ~38 MB model loads once.
      this.extractor = extractor;
      this.ownsExtractor = false;
    } else {
      const config = new SpeakerEmbeddingExtractorConfig();
      config.model = modelPath;
      config.numThreads = numThreads;
      config.debug = false;
      // rawfile 加载器只能吃 rawfile 相对路径;把 resourceManager 传给一个绝对路径会让 native 端
      // 按 rawfile 找不到而 abort(与 Runtime.getOrCreateSpeakerExtractor 同一守卫,也与下方 readWaveSamples 一致)。
      const rm = modelPath.startsWith('/') ? undefined : context?.resourceManager;
      this.extractor = new SpeakerEmbeddingExtractor(config, rm);
      this.ownsExtractor = true;
    }
  }

  get embeddingDim(): number {
    return this.extractor.dim;
  }

  enroll(segments: Float32Array[], sampleRate: number = SPEAKER_SAMPLE_RATE_HZ): Float32Array {
    this.ensureOpen();
    if (segments.length === 0) throw new Error('enroll() needs at least 1 segment');
    if (sampleRate !== SPEAKER_SAMPLE_RATE_HZ) throw new Error('SpeakerEnroller only supports 16 kHz PCM');
    const embeddings: Float32Array[] = [];
    for (let i = 0; i < segments.length; i++) {
      if (segments[i].length === 0) continue;
      embeddings.push(this.computeEmbedding(segments[i], sampleRate));
    }
    if (embeddings.length === 0) throw new Error('all enrollment segments are empty');
    return meanNormalize(embeddings, this.extractor.dim);
  }

  /** 每份样本的独立归一化嵌入（缺陷 #97：多模板取最大，不合并质心）。 */
  enrollFileTemplates(audioPaths: string[]): Float32Array[] {
    this.ensureOpen();
    if (audioPaths.length === 0) throw new Error('enrollFileTemplates() needs at least 1 audio path');
    const out: Float32Array[] = [];
    for (let i = 0; i < audioPaths.length; i++) {
      const segment = this.readWaveSamples(audioPaths[i]);
      if (segment.length === 0) continue;
      out.push(this.computeEmbedding(segment, SPEAKER_SAMPLE_RATE_HZ));
    }
    if (out.length === 0) throw new Error('all enrollment segments are empty');
    return out;
  }

  /**
   * 每份样本按 SEGMENT_TEMPLATE_SECONDS 窗切出的分段模板（只供 final 打分，见文件头注释）。
   * 静音块跳过；样本短于一个窗时整段作为一个分段。
   */
  enrollFileSegmentTemplates(audioPaths: string[]): Float32Array[] {
    this.ensureOpen();
    const out: Float32Array[] = [];
    const window = Math.round(SEGMENT_TEMPLATE_SECONDS * SPEAKER_SAMPLE_RATE_HZ);
    const hop = Math.round(SEGMENT_TEMPLATE_HOP_SECONDS * SPEAKER_SAMPLE_RATE_HZ);
    for (let i = 0; i < audioPaths.length; i++) {
      const samples = this.readWaveSamples(audioPaths[i]);
      if (samples.length === 0) continue;
      if (samples.length <= window) {
        if (rmsOf(samples) >= SEGMENT_TEMPLATE_MIN_RMS) out.push(this.computeEmbedding(samples, SPEAKER_SAMPLE_RATE_HZ));
        continue;
      }
      for (let start = 0; start + window <= samples.length; start += hop) {
        const segment = samples.subarray(start, start + window);
        if (rmsOf(segment) < SEGMENT_TEMPLATE_MIN_RMS) continue;
        out.push(this.computeEmbedding(segment, SPEAKER_SAMPLE_RATE_HZ));
      }
    }
    return out;
  }

  enrollFiles(audioPaths: string[]): Float32Array {
    this.ensureOpen();
    if (audioPaths.length === 0) throw new Error('enrollFiles() needs at least 1 audio path');
    const segments: Float32Array[] = [];
    for (let i = 0; i < audioPaths.length; i++) {
      segments.push(this.readWaveSamples(audioPaths[i]));
    }
    return this.enroll(segments, SPEAKER_SAMPLE_RATE_HZ);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    // A pooled extractor belongs to AmphionRuntime and is released by unloadModel()/unloadRuntime().
    if (this.ownsExtractor) this.extractor.close();
  }

  private ensureOpen(): void {
    if (this.closed) throw new Error('SpeakerEnroller is closed');
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
      if (rawWave.sampleRate !== SPEAKER_SAMPLE_RATE_HZ) throw new Error(`voiceprint sample ${path} must be 16 kHz`);
      return rawWave.samples;
    }
    const fp = fileIo.openSync(path);
    try {
      const stat = fileIo.statSync(fp.fd);
      const buffer = new ArrayBuffer(stat.size);
      fileIo.readSync(fp.fd, buffer);
      const wave = readWaveFromBinary(new Uint8Array(buffer)) as Samples;
      if (wave.sampleRate !== SPEAKER_SAMPLE_RATE_HZ) throw new Error(`voiceprint sample ${path} must be 16 kHz`);
      return wave.samples;
    } finally {
      fileIo.closeSync(fp);
    }
  }
}

function rmsOf(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
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
