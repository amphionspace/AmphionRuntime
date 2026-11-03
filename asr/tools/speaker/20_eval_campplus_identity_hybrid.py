"""阶段 B（sherpa venv）：按到达顺序增量聚类，评分并扫阈值 + 留一标定。

对照臂与混合臂用**同一套分段**（Sortformer 的活跃段），差别只在身份怎么定：
- 对照：取该段的 Sortformer 主槽位
- 混合：CAM++ 嵌入 + 按到达顺序增量分配（新人开档 / 并入已有，上限 4 人）
"""
import os, sys, wave, json, itertools
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


def cluster(turns, thr, cap=MAX_SPK):
    """按到达顺序增量分配身份。返回每段的身份 id。"""
    cents, counts, ids = [], [], []
    for t in turns:
        e = t["emb"]
        if cents:
            sims = np.array([c @ e for c in cents])
            b = int(np.argmax(sims))
            best = float(sims[b])
        else:
            b, best = -1, -1.0
        if b >= 0 and best >= thr:
            k = b
        elif len(cents) < cap:
            cents.append(e.copy())
            counts.append(0)
            k = len(cents) - 1
        else:
            k = b          # 满员且都不够像，只能并入最近的
        c = cents[k] * counts[k] + e
        counts[k] += 1
        n = np.linalg.norm(c)
        cents[k] = c / n if n > 0 else c
        ids.append(k)
    return ids


def composite(label):
    return label.count("_") >= 3          # 如 100350-257_H_I_J，标注员未分开


def assign(rec, ids):
    """把人工标注段映射到身份：取重叠最多的发言段。"""
    tl = TURNS[rec]
    out = []
    for r in refs.get(rec, []):
        rb, re_ = r["begin"], r["begin"] + r["dur"]
        best, bov = -1, 0.0
        for i, t in enumerate(tl):
            ov = max(0.0, min(re_, t["end"]) - max(rb, t["begin"]))
            if ov > bov:
                bov, best = ov, i
        out.append(dict(spk=r["spk"], ident=(ids[best] if best >= 0 else -1)))
    return out


def score(rows_by_rec):
    so = sn = do = dn = 0
    for rec, rows in rows_by_rec.items():
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


base = {rec: assign(rec, [t["slot"] for t in TURNS[rec]]) for rec in NAME}
b = score(base)
print("【对照】Sortformer 槽位（同一套分段）：同人 %d/%d  异人 %d/%d  合计 %d/%d"
      % (b[0], b[1], b[2], b[3], b[0] + b[2], b[1] + b[3]))

print("\n【混合】阈值扫描：")
THR = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
for thr in THR:
    ids = {rec: cluster(TURNS[rec], thr) for rec in NAME}
    rows = {rec: assign(rec, ids[rec]) for rec in NAME}
    s = score(rows)
    print("  thr=%.2f  同人 %2d/%d  异人 %2d/%d  合计 %2d/%d   各录音身份数 %s"
          % (thr, s[0], s[1], s[2], s[3], s[0] + s[2], s[1] + s[3],
             [len(set(ids[r])) for r in NAME]))

print("\n【留一标定】在其余 3 条上选阈值，在留出那条上评：")
tot_o = tot_n = 0
for held in NAME:
    others = [r for r in NAME if r != held]
    accs = []
    for thr in THR:
        ids = {r: cluster(TURNS[r], thr) for r in others}
        rows = {r: assign(r, ids[r]) for r in others}
        s = score(rows)
        n = s[1] + s[3]
        accs.append(((s[0] + s[2]) / n if n else 0.0, thr))
    bestacc = max(a for a, _ in accs)
    # 并列时取最优平台的**中点**，不取最低边缘：标定集小的时候曲线是平的，
    # 取最低边缘会选到过度合并的阈值（实测留出 111223-816 时选到 0.25，结果 9/21）。
    plateau = [t for a, t in accs if a == bestacc]
    bestthr = plateau[len(plateau) // 2]
    ids = {held: cluster(TURNS[held], bestthr)}
    rows = {held: assign(held, ids[held])}
    s = score(rows)
    n, o = s[1] + s[3], s[0] + s[2]
    tot_o += o
    tot_n += n
    tail = "" if n else "   （该条无可判对：标签全为复合）"
    print("  留出 %-42s 标定 thr=%.2f  该条 %2d/%-2d%s" % (NAME[held], bestthr, o, n, tail))
print("  留一合计 %d/%d = %.0f%%" % (tot_o, tot_n, tot_o / max(1, tot_n) * 100))
