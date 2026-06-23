export class SpeakerEnroller {
  private modelPath: string;

  constructor(modelPath: string) {
    this.modelPath = modelPath;
  }

  enroll(audioPaths: string[]): Float32Array {
    // 占位实现：保持 API 与声纹注册流程可用。M5 native 接入后用 SpeakerEmbeddingExtractor 替换。
    const dim = 192;
    const embedding = new Float32Array(dim);
    let seed = this.modelPath.length + audioPaths.length * 31;
    for (const p of audioPaths) {
      for (let i = 0; i < p.length; i++) seed = (seed * 131 + p.charCodeAt(i)) & 0x7fffffff;
    }
    let norm = 0;
    for (let i = 0; i < dim; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      embedding[i] = ((seed % 2000) - 1000) / 1000.0;
      norm += embedding[i] * embedding[i];
    }
    norm = Math.sqrt(norm);
    if (norm > 0) {
      for (let i = 0; i < dim; i++) embedding[i] = embedding[i] / norm;
    }
    return embedding;
  }
}
