// 角色分离用的近期 PCM 环形缓冲，按**绝对样本位置**索引。
//
// 为什么需要它：声纹身份要按发言段算嵌入，而发言段是在块提交（9.92 s）时才由 Sortformer
// 报出来的，`SpeakerDiarizationSession.append()` 原先只是把 PCM 转发给推理客户端、不留存。
// 这里分流一份，供身份判定按轨道时间回取音频。
//
// 契约里最重要的一条：**取不到就返回 undefined，绝不返回部分或错位的音频**。嵌入拿到错位
// 音频会安静地判错身份，比直接说"这段没法判"糟得多。

const BYTES_PER_SAMPLE: number = 2;          // int16 LE，与 append 的入参一致
/** 默认保留时长。发言段最远来自刚提交的那个块（9.92 s），30 s 留足余量给收尾路径。 */
export const PCM_WINDOW_RETAIN_SECONDS: number = 30;

export class DiarizationPcmWindow {
  private readonly sampleRate: number;
  private readonly capacity: number;
  private readonly buffer: Int16Array;
  /** 自 reset 以来写入的总样本数，即绝对位置的上界。 */
  private written: number = 0;

  constructor(sampleRate: number, retainSeconds: number = PCM_WINDOW_RETAIN_SECONDS) {
    this.sampleRate = Math.max(1, Math.round(sampleRate));
    this.capacity = Math.max(1, Math.round(this.sampleRate * Math.max(0.001, retainSeconds)));
    this.buffer = new Int16Array(this.capacity);
  }

  /** 追加一段 int16 LE PCM。字节数为奇数时丢弃末尾那个不完整样本。 */
  append(pcm: ArrayBuffer): void {
    const samples = new Int16Array(pcm, 0, Math.floor(pcm.byteLength / BYTES_PER_SAMPLE));
    for (let index = 0; index < samples.length; index++) {
      this.buffer[(this.written + index) % this.capacity] = samples[index];
    }
    this.written += samples.length;
  }

  /** 仍可取回的最早绝对样本位置。 */
  earliestSample(): number {
    return Math.max(0, this.written - this.capacity);
  }

  totalSamples(): number {
    return this.written;
  }

  /**
   * 按毫秒区间取回音频，归一化为 [-1, 1] 的 Float32Array。
   *
   * 区间必须**完整落在**仍保留的范围内；越界、已被覆盖、或区间为空都返回 undefined。
   */
  slice(beginMs: number, endMs: number): Float32Array | undefined {
    if (!Number.isFinite(beginMs) || !Number.isFinite(endMs)) return undefined;
    const begin = Math.round(beginMs * this.sampleRate / 1000);
    const end = Math.round(endMs * this.sampleRate / 1000);
    if (end <= begin || begin < 0) return undefined;
    if (begin < this.earliestSample() || end > this.written) return undefined;
    const out = new Float32Array(end - begin);
    for (let index = 0; index < out.length; index++) {
      out[index] = this.buffer[(begin + index) % this.capacity] / 32768;
    }
    return out;
  }

  /** 会话结束时清空。 */
  reset(): void {
    this.written = 0;
    this.buffer.fill(0);
  }
}
