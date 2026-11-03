"""CAM++ 身份分配的主机侧评测：对照臂、阈值扫描、留一标定、最短时长门槛扫描。

对照臂与混合臂用**同一套分段**（Sortformer 的逐槽位活跃段，见 19_），差别只在身份怎么定：
- 对照：取该段的 Sortformer 主槽位
- 混合：CAM++ 嵌入 + 按到达顺序增量分配（新人开档 / 并入已有，上限 4 人）

本脚本的 assign_identities() 就是要落到 SDK 的算法本体，保持与两端实现逐条一致。

用法（需先跑 19_）：
    SCRATCH=<中间产物目录> .venv-speaker/bin/python asr/tools/speaker/20_eval_campplus_identity_hybrid.py
"""
import itertools
import json
import os
import wave

import numpy as np
import sherpa_onnx

EVAL = os.path.expanduser("~/.cache/amphion-runtime/customer-inputs-20261030/dq5-diar-eval-20261027")
S = os.environ["SCRATCH"]
AUD = os.path.expanduser("~/Downloads/dingqiao-meeting-20260918/audio")
NAME = {
    "meetingMinutes-20260918-100350-257": "meetingMinutes-20260918-100350-257.wav",
    "meetingMinutes-20260918-102010-230": "meetingMinutes-20260918-102010-230.wav",
    "meetingMinutes-20260918-111223-816": "meetingMinutes-20260918-111223-816.wav",
    "会议-离线-无角色4": "meeting-offline-unknown4.wav",
}
MAX_SPK = 4
UNASSIGNED = -1

ex = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
    model="asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/campplus.onnx",
    num_threads=4, provider="cpu"))

TURNS = json.load(open(os.path.join(S, "sf_turns_perslot.json")))
refs = {}
for line in open(os.path.join(EVAL, "reference-human-partial.rttm"), encoding="utf-8"):
    p = line.split()
    refs.setdefault(p[1], []).append(dict(begin=float(p[3]), dur=float(p[4]), spk=p[7]))


def load(rec):
    w = wave.open(os.path.join(AUD, NAME[rec]), "rb")
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    return a


def embed(x):
    st = ex.create_stream()
    st.accept_waveform(16000, x)
    st.input_finished()
    v = np.array(ex.compute(st), dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


for rec in NAME:
    a = load(rec)
    for t in TURNS[rec]:
        t["emb"] = embed(a[int(t["begin"] * 16000):int(t["end"] * 16000)])


# ---------------------------------------------------------------- 算法本体
def assign_identities(turns, threshold=0.45, min_assign_seconds=0.5, cap=MAX_SPK):
    """按到达顺序给每个发言段分配身份。返回 [(identity, confidence)]。

    - 嵌入必须已 L2 归一，余弦即点积
    - 短于 min_assign_seconds 的段不赋身份、也不更新质心（宁可留"不确定"，不乱贴）。
      实测 1.0s 门槛要牺牲 13% 的发言段换零准确率收益，故取 0.5s（损 2%）；
      这组数据的参考段最短 1.27s，测不出门槛本来要防的短段危害，所以保留一个低门槛。
    - confidence：并入已有身份时为余弦相似度；新开身份时为 0（没有可比先验）
    - 质心在整个会话内保留；满员且都不够像时并入最近的
    """
    centroids, counts, out = [], [], []
    for t in turns:
        duration = t["end"] - t["begin"]
        if duration < min_assign_seconds:
            out.append((UNASSIGNED, 0.0))
            continue
        e = t["emb"]
        if centroids:
            sims = np.array([c @ e for c in centroids])
            best = int(np.argmax(sims))
            score = float(sims[best])
        else:
            best, score = -1, -1.0
        if best >= 0 and score >= threshold:
            k, confidence = best, score
        elif len(centroids) < cap:
            centroids.append(e.copy())
            counts.append(0)
            k, confidence = len(centroids) - 1, 0.0   # 新开身份没有可比的先验
        else:
            k, confidence = best, max(0.0, score)      # 满员只能并入最近的，相似度照实报
        c = centroids[k] * counts[k] + e
        counts[k] += 1
        n = np.linalg.norm(c)
        centroids[k] = c / n if n > 0 else c
        out.append((k, confidence))
    return out


def composite(label):
    return label.count("_") >= 3          # 如 100350-257_H_I_J，标注员未分开


def map_refs(rec, idents):
    """把人工标注段映射到身份：取重叠最多的发言段。"""
    tl = TURNS[rec]
    rows = []
    for r in refs.get(rec, []):
        rb, re_ = r["begin"], r["begin"] + r["dur"]
        best, bov = -1, 0.0
        for i, t in enumerate(tl):
            ov = max(0.0, min(re_, t["end"]) - max(rb, t["begin"]))
            if ov > bov:
                bov, best = ov, i
        rows.append(dict(spk=r["spk"], ident=(idents[best] if best >= 0 else UNASSIGNED)))
    return rows


def score(rows_by_rec):
    so = sn = do = dn = 0
    for rows in rows_by_rec.values():
        for A, B in itertools.combinations(rows, 2):
            if A["ident"] < 0 or B["ident"] < 0:
                continue
            if A["spk"] == B["spk"]:
                if composite(A["spk"]):
                    continue
                sn += 1
                so += (A["ident"] == B["ident"])
            else:
                dn += 1
                do += (A["ident"] != B["ident"])
    return so, sn, do, dn


def run(threshold, min_assign):
    ids = {rec: [k for k, _ in assign_identities(TURNS[rec], threshold, min_assign)] for rec in NAME}
    return score({rec: map_refs(rec, ids[rec]) for rec in NAME}), ids


base = {rec: map_refs(rec, [t["slot"] for t in TURNS[rec]]) for rec in NAME}
b = score(base)
print("【对照】Sortformer 槽位（同一套分段）：同人 %d/%d  异人 %d/%d  合计 %d/%d"
      % (b[0], b[1], b[2], b[3], b[0] + b[2], b[1] + b[3]))

THR = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
print("\n【混合】阈值扫描（无最短时长门槛）：")
for thr in THR:
    s, ids = run(thr, 0.0)
    print("  thr=%.2f  同人 %2d/%d  异人 %2d/%d  合计 %2d/%d   各录音身份数 %s"
          % (thr, s[0], s[1], s[2], s[3], s[0] + s[2], s[1] + s[3],
             [len(set(k for k in ids[r] if k >= 0)) for r in NAME]))

print("\n【最短时长门槛扫描】（阈值固定在平台中点 0.45）：")
for ma in (0.0, 0.5, 1.0, 1.5, 2.0):
    s, ids = run(0.45, ma)
    dropped = sum(1 for r in NAME for k in ids[r] if k < 0)
    total = sum(len(ids[r]) for r in NAME)
    print("  最短 %.1fs  合计 %2d/%-2d  未赋身份的段 %d/%d（%.0f%%）"
          % (ma, s[0] + s[2], s[1] + s[3], dropped, total, dropped / total * 100))

print("\n【留一标定】在其余 3 条上选阈值（取最优平台中点），在留出那条上评：")
tot_o = tot_n = 0
for held in NAME:
    others = [r for r in NAME if r != held]
    accs = []
    for thr in THR:
        ids = {r: [k for k, _ in assign_identities(TURNS[r], thr)] for r in others}
        s = score({r: map_refs(r, ids[r]) for r in others})
        n = s[1] + s[3]
        accs.append(((s[0] + s[2]) / n if n else 0.0, thr))
    bestacc = max(a for a, _ in accs)
    # 并列时取最优平台的中点，不取最低边缘：标定集小的时候曲线是平的，
    # 取最低边缘会选到过度合并的阈值（实测留出 111223-816 时选到 0.25，结果 9/21）。
    plateau = [t for a, t in accs if a == bestacc]
    bestthr = plateau[len(plateau) // 2]
    ids = [k for k, _ in assign_identities(TURNS[held], bestthr)]
    s = score({held: map_refs(held, ids)})
    n, o = s[1] + s[3], s[0] + s[2]
    tot_o += o
    tot_n += n
    tail = "" if n else "   （该条无可判对：标签全为复合）"
    print("  留出 %-42s 标定 thr=%.2f  该条 %2d/%-2d%s" % (NAME[held], bestthr, o, n, tail))
print("  留一合计 %d/%d = %.0f%%" % (tot_o, tot_n, tot_o / max(1, tot_n) * 100))
