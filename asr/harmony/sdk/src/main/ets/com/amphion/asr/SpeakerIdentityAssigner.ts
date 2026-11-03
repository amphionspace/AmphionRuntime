/**
 * 按到达顺序给发言段分配说话人身份：声纹嵌入 + 增量质心。
 *
 * 为什么需要它：Sortformer 的四个槽位在"三人依次讲话"这类排列上会把不同的人并成一个
 * （主机实测 10 组只有 4 组正确，真机同口径 10/10 复现），而且是高置信度误并
 * （第 2 人在本该属于它的槽位上最大概率仅 0.030），调阈值、延长发言、全上下文重跑都无效。
 * 声纹嵌入在同一批材料上可分（同人最小 0.535、异人最大 0.338，余量 0.197），所以这里让
 * Sortformer 只管"何时有人说话"，身份改由嵌入决定。
 *
 * 本文件是**纯算术**：不读音频、不碰模型，嵌入由调用方给。与安卓
 * `SpeakerIdentityAssigner.kt` 逐条镜像，常量必须一致；门禁见
 * `asr/tools/tests/test_harmony_speaker_identity_assigner.py`（用 node 执行本文件）。
 * 主机评测与定参见 `asr/tools/speaker/20_eval_campplus_identity_hybrid.py`。
 */

/** 并入已有身份所需的最小余弦相似度。 */
export const IDENTITY_MERGE_THRESHOLD: number = 0.45;
/**
 * 短于这个时长的发言段不赋身份、也不更新质心。
 *
 * 实测 1.0 s 门槛要牺牲 13% 的发言段换**零**准确率收益，故取 0.5 s（损 2%）。
 * 评测数据的参考段最短 1.27 s，测不出门槛本来要防的短段危害，所以保留一个低门槛而非去掉。
 */
export const IDENTITY_MIN_ASSIGN_SECONDS: number = 0.5;
/** 未赋身份。与公开 `speakerIndex` 的"不确定"取值一致。 */
export const IDENTITY_UNASSIGNED: number = -1;

export class SpeakerIdentityDecision {
  /** 身份编号，或 [IDENTITY_UNASSIGNED]。 */
  identity: number;
  /** 并入已有身份时为余弦相似度；新开身份时为 0（没有可比先验）。 */
  confidence: number;

  constructor(identity: number, confidence: number) {
    this.identity = identity;
    this.confidence = confidence;
  }
}

function dot(a: Float32Array, b: Float32Array): number {
  let sum = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) sum += a[i] * b[i];
  return sum;
}

function normalized(v: Float32Array): Float32Array {
  let sum = 0;
  for (let i = 0; i < v.length; i++) sum += v[i] * v[i];
  const norm = Math.sqrt(sum);
  if (norm <= 0) return v.slice();
  const out = new Float32Array(v.length);
  for (let i = 0; i < v.length; i++) out[i] = v[i] / norm;
  return out;
}

export class SpeakerIdentityAssigner {
  private centroids: Float32Array[] = [];
  private counts: number[] = [];
  private maxSpeakers: number;
  private threshold: number;
  private minAssignSeconds: number;

  constructor(maxSpeakers: number, threshold: number = IDENTITY_MERGE_THRESHOLD,
    minAssignSeconds: number = IDENTITY_MIN_ASSIGN_SECONDS) {
    this.maxSpeakers = Math.max(1, Math.round(maxSpeakers));
    this.threshold = threshold;
    this.minAssignSeconds = Math.max(0, minAssignSeconds);
  }

  /**
   * 处理一个发言段。必须按到达顺序调用：质心是增量更新的，顺序影响结果。
   *
   * @param embedding 该段的声纹嵌入；内部会再归一化一次，调用方不必保证。
   * @param durationSeconds 该段时长，短于 [IDENTITY_MIN_ASSIGN_SECONDS] 则不赋身份。
   */
  assign(embedding: Float32Array, durationSeconds: number): SpeakerIdentityDecision {
    if (durationSeconds < this.minAssignSeconds || embedding.length === 0) {
      return new SpeakerIdentityDecision(IDENTITY_UNASSIGNED, 0);
    }
    const e = normalized(embedding);
    let best = -1;
    let score = -1;
    for (let i = 0; i < this.centroids.length; i++) {
      const s = dot(this.centroids[i], e);
      if (s > score) {
        score = s;
        best = i;
      }
    }

    let k: number;
    let confidence: number;
    if (best >= 0 && score >= this.threshold) {
      k = best;
      confidence = score;
    } else if (this.centroids.length < this.maxSpeakers) {
      this.centroids.push(e.slice());
      this.counts.push(0);
      k = this.centroids.length - 1;
      confidence = 0;                     // 新开身份没有可比的先验
    } else {
      k = best;                           // 满员且都不够像，只能并入最近的
      confidence = Math.max(0, score);
    }

    // 质心 = 历史均值与本段的归一化合成；count 从 0 起，所以首次更新后质心就是该段嵌入
    const centroid = this.centroids[k];
    const merged = new Float32Array(centroid.length);
    for (let i = 0; i < centroid.length; i++) {
      merged[i] = centroid[i] * this.counts[k] + (i < e.length ? e[i] : 0);
    }
    this.counts[k] += 1;
    this.centroids[k] = normalized(merged);
    return new SpeakerIdentityDecision(k, confidence);
  }

  /** 已开出的身份数。 */
  identityCount(): number {
    return this.centroids.length;
  }

  /**
   * 清空。**不要**按 120 s 公共提交周期调用：质心必须在整个会话内保留，否则身份每个周期
   * 重新编号，那本身就是"角色错乱"的一种形态。只在会话结束时清。
   */
  reset(): void {
    this.centroids = [];
    this.counts = [];
  }
}
