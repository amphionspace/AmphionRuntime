"""阶段 A2（ORT venv）：改为**逐槽位**切发言段。

上一版用"任一槽位活跃"切段，一段会跨说话人，对混合段算嵌入必然判不准（对照臂也因此
从 28/34 掉到 18/34）。产品侧是按槽位累积轨道的，这里对齐：对每个槽位单独取其活跃
连续段，段自带该槽位编号。
"""
import os, sys, wave, json
import numpy as np

EVAL = os.path.expanduser("~/.cache/amphion-runtime/customer-inputs-20261030/dq5-diar-eval-20261027")
sys.path.insert(0, EVAL)
PKG = os.environ["SF_PKG"]
OUT = os.environ["SCRATCH"]
AUD = os.path.expanduser("~/Downloads/dingqiao-meeting-20260918/audio")
NAME = {
    "meetingMinutes-20260918-100350-257": "meetingMinutes-20260918-100350-257.wav",
    "meetingMinutes-20260918-102010-230": "meetingMinutes-20260918-102010-230.wav",
    "meetingMinutes-20260918-111223-816": "meetingMinutes-20260918-111223-816.wav",
    "会议-离线-无角色4": "meeting-offline-unknown4.wav",
}
GAP_MS = 300
MIN_TURN = 0.4
import sf_infer


def runs(mask, gap, min_frames):
    out = []
    i, n = 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n:
            if mask[j]:
                j += 1
                continue
            k = j
            while k < n and k - j < gap and not mask[k]:
                k += 1
            if k < n and mask[k]:
                j = k
            else:
                break
        if j - i >= min_frames:
            out.append((i, j))
        i = j + 1
    return out


m = sf_infer.Sortformer(PKG, encoder="int8ort1163", threads=8)
res = {}
for rec, fn in NAME.items():
    w = wave.open(os.path.join(AUD, fn), "rb")
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    probs = m.run(a)
    act = probs >= 0.5
    turns = []
    for slot in range(4):
        for i, j in runs(act[:, slot], GAP_MS // 10, int(MIN_TURN * 100)):
            turns.append(dict(begin=i / 100.0, end=j / 100.0, slot=slot))
    turns.sort(key=lambda t: t["begin"])          # 按到达顺序
    res[rec] = turns
    per = [sum(1 for t in turns if t["slot"] == s) for s in range(4)]
    d = [t["end"] - t["begin"] for t in turns]
    print("  %-42s %6.1fs  逐槽位段数 %s  共 %d 段  段长中位 %.2fs  合计 %.1fs"
          % (fn, len(a) / 16000, per, len(turns), np.median(d) if d else 0, sum(d)))
json.dump(res, open(os.path.join(OUT, "sf_turns_perslot.json"), "w"), ensure_ascii=False)
print("已写 sf_turns_perslot.json")
