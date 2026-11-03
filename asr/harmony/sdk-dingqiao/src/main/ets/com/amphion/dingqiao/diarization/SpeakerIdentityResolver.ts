import { DiarizationPcmWindow, PCM_WINDOW_RETAIN_SECONDS } from './DiarizationPcmWindow';
import { SpeakerIdentityAssigner } from 'amphion_asr';

// 把 Sortformer 的发言段换成声纹身份：取回该段音频 -> 算嵌入 -> 增量分配。
//
// 嵌入函数是**注入**的，不在这里加载模型：既让本文件能在没有 38 MB 声纹模型的环境下完整
// 单测，也让调用方复用 AmphionRuntime 的共享 extractor 池（模型只加载一次）。
//
// 时序约束：嵌入必须在**会话期间**逐段算完，提交与收尾路径只做分配器那几微秒的算术。
// 原因是收尾路径余量很小——对外声明 1.1~2.4 s，实测 1652~1732 ms，压测预算 2000 ms，
// 只剩约 300 ms，把嵌入堆在 finish 会顶破它。

/** 给一段 16 kHz 单声道音频算声纹嵌入；算不出时返回 undefined。 */
export type SpeakerEmbedFn = (samples: Float32Array) => Float32Array | undefined;

/** 未赋身份。与公开 speakerIndex 的"不确定"取值一致。 */
export const IDENTITY_UNRESOLVED: number = -1;

export class SpeakerIdentityResolver {
  private readonly window: DiarizationPcmWindow;
  private readonly assigner: SpeakerIdentityAssigner;
  private readonly embed: SpeakerEmbedFn;
  /** 取不到音频的段数，用于诊断：持续非零说明保留窗太短或轨道报得太晚。 */
  private audioMisses: number = 0;
  /** 嵌入失败的段数。 */
  private embedFailures: number = 0;

  constructor(sampleRate: number, maxSpeakers: number, embed: SpeakerEmbedFn,
    retainSeconds: number = PCM_WINDOW_RETAIN_SECONDS) {
    this.window = new DiarizationPcmWindow(sampleRate, retainSeconds);
    this.assigner = new SpeakerIdentityAssigner(maxSpeakers);
    this.embed = embed;
  }

  /** 分流一份近期 PCM。必须与喂给推理客户端的是同一批字节、同一顺序。 */
  appendAudio(pcm: ArrayBuffer): void {
    this.window.append(pcm);
  }

  /**
   * 给一批 final 轨道定身份，返回与入参**同序**的身份数组。
   *
   * 轨道内部按起始时间排序后再分配：分配器是增量的，顺序会影响编号，而 Sortformer 是按
   * 槽位报 runs 的（槽位 0 的全部、再槽位 1 的……），不排序会把到达顺序弄乱。
   *
   * 取不到音频或嵌入失败的段返回 [IDENTITY_UNRESOLVED]，不猜。
   */
  resolve(tracks: number[][]): number[] {
    const order: number[] = [];
    for (let index = 0; index < tracks.length; index++) order.push(index);
    order.sort((a, b) => tracks[a][0] - tracks[b][0]);

    const identities: number[] = new Array<number>(tracks.length).fill(IDENTITY_UNRESOLVED);
    for (const index of order) {
      const track = tracks[index];
      const samples = this.window.slice(track[0], track[1]);
      if (samples === undefined) {
        this.audioMisses += 1;
        continue;
      }
      const embedding = this.embed(samples);
      if (embedding === undefined || embedding.length === 0) {
        this.embedFailures += 1;
        continue;
      }
      const decision = this.assigner.assign(embedding, (track[1] - track[0]) / 1000);
      identities[index] = decision.identity;
    }
    return identities;
  }

  /** 已开出的身份数。 */
  identityCount(): number {
    return this.assigner.identityCount();
  }

  /** 诊断计数：取不到音频的段数。 */
  audioMissCount(): number {
    return this.audioMisses;
  }

  /** 诊断计数：嵌入失败的段数。 */
  embedFailureCount(): number {
    return this.embedFailures;
  }

  /** 会话结束时清空。**不要**按 120 s 公共提交周期调用，否则身份每周期重新编号。 */
  reset(): void {
    this.window.reset();
    this.assigner.reset();
    this.audioMisses = 0;
    this.embedFailures = 0;
  }
}
