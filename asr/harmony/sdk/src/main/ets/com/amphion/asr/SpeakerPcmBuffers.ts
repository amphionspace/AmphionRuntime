export class SpeakerPcmBuffers {
  private maxSamples: number;
  private speakerVadParts: Float32Array[] = [];
  private fallbackParts: Float32Array[] = [];
  private speakerVadSampleCount: number = 0;
  private fallbackSampleCount: number = 0;
  // 回退缓冲自上次清空以来观测到的样本总数，不受 maxSamples 封顶；配合调用方给出的
  // "语音结束之后又喂进来的样本数"定位语音结束在缓冲里的位置。
  private fallbackObservedCount: number = 0;
  // 每次清空公开句缓冲递增。投机算好的 final 分数只能在同一代缓冲上消费。
  private fallbackEpochValue: number = 0;

  constructor(maxSamples: number) {
    this.maxSamples = Math.max(1, Math.round(maxSamples));
  }

  observe(samples: Float32Array, captureSpeakerVad: boolean, captureFallback: boolean): void {
    if (captureSpeakerVad) {
      const retained = Math.min(samples.length, this.maxSamples - this.speakerVadSampleCount);
      if (retained > 0) {
        this.speakerVadParts.push(samples.slice(0, retained));
        this.speakerVadSampleCount += retained;
      }
    }
    if (captureFallback) {
      this.fallbackObservedCount += samples.length;
      const retained = Math.min(samples.length, this.maxSamples - this.fallbackSampleCount);
      if (retained > 0) {
        this.fallbackParts.push(samples.slice(0, retained));
        this.fallbackSampleCount += retained;
      }
    }
  }

  speakerVadLength(): number {
    return this.speakerVadSampleCount;
  }

  speakerVadTail(n: number): Float32Array {
    const all = concatFloat32(this.speakerVadParts, this.speakerVadSampleCount);
    if (all.length <= n) return all;
    return all.slice(all.length - n, all.length);
  }

  fallbackSamples(): Float32Array {
    return concatFloat32(this.fallbackParts, this.fallbackSampleCount);
  }

  fallbackEpoch(): number {
    return this.fallbackEpochValue;
  }

  /**
   * 回退 PCM 截到语音结束处。`trailingSamples` 是语音结束之后又观测到的样本数（由 VAD
   * 时钟给出）；用差值而不是绝对位置，是因为缓冲起点与 VAD 时钟起点不一定对齐，而差值
   * 对调用方的分块方式也不敏感。语音结束落在封顶之后时按封顶长度返回。
   */
  fallbackSpeechSamples(trailingSamples: number): Float32Array {
    const trailing = Math.max(0, Math.round(trailingSamples));
    const end = Math.max(0, Math.min(this.fallbackSampleCount, this.fallbackObservedCount - trailing));
    if (end >= this.fallbackSampleCount) return this.fallbackSamples();
    const out = new Float32Array(end);
    let offset = 0;
    for (let i = 0; i < this.fallbackParts.length && offset < end; i++) {
      const part = this.fallbackParts[i];
      const take = Math.min(part.length, end - offset);
      out.set(take === part.length ? part : part.subarray(0, take), offset);
      offset += take;
    }
    return out;
  }

  clearNativeSegment(): void {
    this.speakerVadParts = [];
    this.speakerVadSampleCount = 0;
  }

  clearPublicUtterance(): void {
    this.fallbackParts = [];
    this.fallbackSampleCount = 0;
    this.fallbackObservedCount = 0;
    this.fallbackEpochValue += 1;
  }

  clearAll(): void {
    this.clearNativeSegment();
    this.clearPublicUtterance();
  }
}

function concatFloat32(parts: Float32Array[], total: number): Float32Array {
  const out = new Float32Array(total);
  let offset = 0;
  for (let i = 0; i < parts.length; i++) {
    out.set(parts[i], offset);
    offset += parts[i].length;
  }
  return out;
}
