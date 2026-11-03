"""角色分离的场景级评分器：DER 三分量 + 人数判对 + 角色覆盖率 + 身份稳定性。

为什么不只看 DER：
- DER 会把"混淆降、漏检升"抹平，所以三分量必须分开报。
- DER 在 UEM 受限口径下看不见"成片无角色输出"（丁桥 100350-257 有 137 秒空洞而 DER 正常），
  所以单列角色覆盖率。
- 客户感知的"角色一被识别为其他角色"是**标签在会话内跳变**，DER 对此不敏感（整体置换后
  DER 可能不变），所以单列身份稳定性。

评分口径与交付一致（openbench-der-v1 / md-eval）：10 ms 栅格、collar 0、计入重叠、
Hungarian 最优置换。核心 der() 逻辑取自交付包自带的 run_dq5.py，保持同口径。
"""
import itertools
from collections import defaultdict

import numpy as np

STEP = 0.01          # 10 ms 栅格


def read_rttm(path, speaker_field=7):
    """返回 [(begin, end, speaker)]。只取 SPEAKER 行。"""
    segs = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) > speaker_field and parts[0] == "SPEAKER":
                begin = float(parts[3])
                segs.append((begin, begin + float(parts[4]), parts[speaker_field]))
    return segs


def _grid(segs, n, keys):
    grid = np.zeros((len(keys), n), bool)
    index = {k: i for i, k in enumerate(keys)}
    for begin, end, key in segs:
        grid[index[key], max(0, int(begin / STEP)):min(n, int(end / STEP))] = True
    return grid


def der(ref, hyp, n, uem=None):
    """与 run_dq5.py 同口径：10 ms 栅格、collar 0、计重叠、Hungarian。"""
    rk = sorted({k for _, _, k in ref})
    hk = sorted({k for _, _, k in hyp})
    R = _grid(ref, n, rk)
    H = _grid(hyp, n, hk) if hk else np.zeros((1, n), bool)
    mask = np.ones(n, bool) if uem is None else uem
    R = R & mask
    H = H & mask
    Nr = R.sum(axis=0)
    Nh = H.sum(axis=0)
    best = None
    for perm in itertools.permutations(range(H.shape[0]), min(len(rk), H.shape[0])):
        matched = np.zeros(n, np.int64)
        for i, h in enumerate(perm):
            matched += (R[i] & H[h])
        miss = int(np.maximum(0, Nr - Nh).sum())
        fa = int(np.maximum(0, Nh - Nr).sum())
        conf = int((np.minimum(Nr, Nh) - matched).sum())
        if best is None or miss + fa + conf < best[0]:
            best = (miss + fa + conf, miss, fa, conf)
    total_errors, miss, fa, conf = best
    total = int(Nr.sum())
    return dict(
        der=(total_errors / total if total else None),
        miss=miss * STEP, fa=fa * STEP, conf=conf * STEP,
        miss_rate=(miss / total if total else None),
        fa_rate=(fa / total if total else None),
        conf_rate=(conf / total if total else None),
        total=total * STEP, ref_spk=len(rk), hyp_spk=len(hk),
    )


def role_coverage(ref, hyp, n):
    """参考认为有人说话的时间里，假设给出了角色的占比。

    专门抓"成片无角色输出"：DER 在 UEM 受限口径下看不见它。
    """
    speech = np.zeros(n, bool)
    for begin, end, _ in ref:
        speech[max(0, int(begin / STEP)):min(n, int(end / STEP))] = True
    covered = np.zeros(n, bool)
    for begin, end, _ in hyp:
        covered[max(0, int(begin / STEP)):min(n, int(end / STEP))] = True
    denom = speech.sum()
    if denom == 0:
        return None
    return float((speech & covered).sum() / denom)


def identity_stability(ref, hyp, n):
    """同一个参考说话人，其时间线上被赋予的假设标签换了几次。

    做法：对每个参考说话人，按时间取其独占区间（避开重叠），看落在这些区间上的
    假设标签序列有多少次变化。整体置换不影响该指标，所以它独立于 DER。

    返回 (变化次数总计, 参考说话人数, 每人平均变化次数)。
    """
    rk = sorted({k for _, _, k in ref})
    R = _grid(ref, n, rk)
    exclusive = R.sum(axis=0) == 1
    hk = sorted({k for _, _, k in hyp})
    H = _grid(hyp, n, hk) if hk else np.zeros((0, n), bool)
    flips_total = 0
    for i in range(len(rk)):
        own = R[i] & exclusive
        if own.sum() == 0:
            continue
        labels = []
        for t in np.flatnonzero(own):
            active = np.flatnonzero(H[:, t]) if H.size else []
            labels.append(int(active[0]) if len(active) == 1 else -1)
        # 压缩连续相同项，忽略 -1（无输出或重叠）造成的空档
        seq = [v for v in labels if v >= 0]
        compressed = [v for j, v in enumerate(seq) if j == 0 or v != seq[j - 1]]
        flips_total += max(0, len(compressed) - 1)
    return flips_total, len(rk), (flips_total / len(rk) if rk else None)


def score_one(ref, hyp, duration, uem=None):
    """一个场次的全部指标。"""
    n = int(duration / STEP) + 1
    out = der(ref, hyp, n, uem)
    out["coverage"] = role_coverage(ref, hyp, n)
    flips, nspk, per = identity_stability(ref, hyp, n)
    out["flips"] = flips
    out["flips_per_speaker"] = per
    out["speaker_count_correct"] = out["ref_spk"] == out["hyp_spk"]
    return out


def segment_stats(segs):
    """场景切片用的描述量：时长、人数、重叠占比、段长分位。"""
    if not segs:
        return {}
    end = max(e for _, e, _ in segs)
    n = int(end / STEP) + 1
    grid = np.zeros(n, np.int16)
    for begin, stop, _ in segs:
        grid[max(0, int(begin / STEP)):min(n, int(stop / STEP))] += 1
    lens = np.array([e - b for b, e, _ in segs])
    return dict(
        duration=end,
        speakers=len({s for _, _, s in segs}),
        segments=len(segs),
        speech_ratio=float((grid > 0).sum() * STEP / end),
        overlap_ratio=float((grid > 1).sum() * STEP / end),
        turn_median=float(np.median(lens)),
        turn_p10=float(np.percentile(lens, 10)),
    )
