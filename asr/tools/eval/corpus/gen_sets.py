"""生成尚未测试指标所需的测试语音。

A digits     车牌/身份证/手机号/计数序列  —— macOS Tingting 合成（唯一可用中文发音人）
B longform   长语音 WER 用，AISHELL-3 同说话人拼接（真人语音）
C diar       角色分离用，2/3/4 人交替发言 + RTTM 真值（真人语音）
D overlap    重叠讲话用，2 人按指定重叠率混合 + RTTM（真人语音）
E trials     声纹 EER 用的 same/diff 试验对清单（复用既有音频，不新增）
"""
import json, os, random, re, subprocess, sys, gzip
from pathlib import Path
import numpy as np
import soundfile as sf

SP = Path(os.environ["SP"])
CORPUS = Path(os.environ["CORPUS"])
OUT = SP / "gensets"
SR = 16000
random.seed(20261025); np.random.seed(20261025)
OUT.mkdir(parents=True, exist_ok=True)

# ---------------- 载入 AISHELL-3（已重采样为 16k 的 clean 集） ----------------
sup = {}
with gzip.open(CORPUS / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz",
               "rt", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        sup[d["recording_id"]] = d
CLEAN = SP / "snrsets" / "clean"
have = {p.stem: p for p in CLEAN.glob("*.wav")}
by_spk = {}
for rid, p in have.items():
    by_spk.setdefault(sup[rid]["speaker"], []).append(rid)
for v in by_spk.values():
    v.sort()
print(f"可用真人音频 {len(have)} 条 / {len(by_spk)} 位说话人", flush=True)

def rd(rid):
    x, sr = sf.read(str(have[rid]), dtype="float64")
    assert sr == SR
    return x

def wr(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    m = np.max(np.abs(x))
    if m > 0.999:
        x = x * (0.999 / m)
    sf.write(str(path), x.astype(np.float32), SR, subtype="PCM_16")

# ================= A. 数字 / 车牌 / 身份证（TTS） =================
D = "零一二三四五六七八九"
YAO = {"一": "幺"}
PROV = list("京津冀晋蒙辽吉黑沪苏浙皖闽赣鲁豫鄂湘粤桂琼渝川贵云藏陕甘青宁新")
LET = list("ABCDEFGHJKLMNPQRSTUVWXYZ")

def say_digits(s, yao=False):
    return "".join(YAO.get(c, c) if yao else c for c in (D[int(ch)] for ch in s))

def gen_phone():
    pre = random.choice(["13", "15", "17", "18", "19"])
    num = pre + "".join(random.choice("0123456789") for _ in range(9))
    return num, f"我的手机号是{say_digits(num, yao=True)}"

def gen_plate():
    p = random.choice(PROV); L = random.choice(LET)
    tail = "".join(random.choice("0123456789") for _ in range(5))
    return f"{p}{L}{tail}", f"车牌号是{p}{L}{say_digits(tail)}"

def gen_id():
    body = "".join(random.choice("0123456789") for _ in range(17))
    last = random.choice("0123456789X")
    num = body + last
    spoken = say_digits(body) + ("X" if last == "X" else D[int(last)])
    return num, f"身份证号是{spoken}"

SEQ = [
    ("count1to10", "一二三四五六七八九十"),
    ("count1to10b", "从一数到十：一二三四五六七八九十"),
    ("countdown", "十九八七六五四三二一"),
    ("odd", "一三五七九"),
    ("even", "二四六八十"),
]

cases = []
for i in range(60):
    k, t = gen_phone(); cases.append((f"phone_{i:03d}", t, k, "phone"))
for i in range(60):
    k, t = gen_plate(); cases.append((f"plate_{i:03d}", t, k, "plate"))
for i in range(40):
    k, t = gen_id();    cases.append((f"id_{i:03d}", t, k, "id"))
for i in range(20):
    nm, t = SEQ[i % len(SEQ)]
    cases.append((f"seq_{i:03d}_{nm}", t, "", "seq"))

print(f"A digits: 合成 {len(cases)} 条（Tingting，速率 170/200/230 轮换）", flush=True)
adir = OUT / "digits" / "clean"
adir.mkdir(parents=True, exist_ok=True)
rates = [170, 200, 230]
meta_a = []
for n, (cid, text, canon, kind) in enumerate(cases):
    rate = rates[n % 3]
    raw = adir / f"{cid}.raw.wav"
    subprocess.run(["say", "-v", "Tingting", "-r", str(rate), "-o", str(raw),
                    "--data-format=LEI16@16000", text], check=True)
    x, sr = sf.read(str(raw), dtype="float64")
    assert sr == SR
    pad = np.zeros(int(0.4 * SR))
    wr(adir / f"{cid}.wav", np.concatenate([pad, x, pad, pad]))   # 首尾留白，避免尾字被截
    raw.unlink()
    meta_a.append({"id": cid, "text": text, "canonical": canon, "kind": kind, "rate": rate})
    if (n + 1) % 40 == 0:
        print(f"  {n+1}/{len(cases)}", flush=True)
(OUT / "digits" / "meta.jsonl").write_text(
    "\n".join(json.dumps(m, ensure_ascii=False) for m in meta_a) + "\n", encoding="utf-8")

# ================= B. 长语音（真人拼接） =================
print("B longform: 拼接 ...", flush=True)
bdir = OUT / "longform" / "clean"
cand = [s for s, v in by_spk.items() if len(v) >= 6]
random.shuffle(cand)
meta_b = []
gap = np.zeros(int(0.35 * SR))
for i, spk in enumerate(cand[:20]):
    rids = by_spk[spk][:]
    random.shuffle(rids)
    segs, texts, total = [], [], 0.0
    for rid in rids:
        x = rd(rid)
        segs.append(x); segs.append(gap)
        texts.append((sup[rid]["text"] or "").strip())
        total += len(x) / SR + 0.35
        if total >= 60:
            break
    # 不足 60s 的用同说话人音频再轮一遍补足
    while total < 60:
        rid = random.choice(rids); x = rd(rid)
        segs.append(x); segs.append(gap)
        texts.append((sup[rid]["text"] or "").strip())
        total += len(x) / SR + 0.35
    y = np.concatenate(segs)
    cid = f"long_{i:02d}_{spk}"
    wr(bdir / f"{cid}.wav", y)
    meta_b.append({"id": cid, "speaker": spk, "duration_sec": round(len(y) / SR, 2),
                   "num_utts": len(texts), "text": "".join(texts)})
(OUT / "longform" / "meta.jsonl").write_text(
    "\n".join(json.dumps(m, ensure_ascii=False) for m in meta_b) + "\n", encoding="utf-8")
print(f"  {len(meta_b)} 条，平均 {np.mean([m['duration_sec'] for m in meta_b]):.1f}s", flush=True)

# ================= C. 角色分离（2/3/4 人交替，带 RTTM） =================
print("C diar: 生成交替发言 ...", flush=True)
cdir = OUT / "diar" / "clean"
meta_c = []
pool = [s for s, v in by_spk.items() if len(v) >= 8]
for nspk in (2, 3, 4):
    for k in range(5):
        spks = random.sample(pool, nspk)
        segs, rttm, t = [], [], 0.0
        turn = 0
        while t < 180:
            spk = spks[turn % nspk]
            # 每轮说 1~3 句，模拟「轮流说话、极少抢话」
            for _ in range(random.randint(1, 3)):
                rid = random.choice(by_spk[spk])
                x = rd(rid)
                segs.append(x)
                rttm.append({"start": round(t, 3), "dur": round(len(x) / SR, 3), "spk": spk})
                t += len(x) / SR
                sil = random.uniform(0.15, 0.45)
                segs.append(np.zeros(int(sil * SR))); t += sil
            gapl = random.uniform(0.3, 0.8)
            segs.append(np.zeros(int(gapl * SR))); t += gapl
            turn += 1
        y = np.concatenate(segs)
        cid = f"diar{nspk}_{k:02d}"
        wr(cdir / f"{cid}.wav", y)
        meta_c.append({"id": cid, "num_speakers": nspk, "speakers": spks,
                       "duration_sec": round(len(y) / SR, 2), "segments": rttm})
(OUT / "diar" / "meta.jsonl").write_text(
    "\n".join(json.dumps(m, ensure_ascii=False) for m in meta_c) + "\n", encoding="utf-8")
print(f"  {len(meta_c)} 条（2/3/4 人各 5 条，各约 180s）", flush=True)

# ================= D. 重叠讲话（受控重叠率） =================
print("D overlap: 生成重叠混合 ...", flush=True)
ddir = OUT / "overlap" / "clean"
meta_d = []
for ratio in (0.10, 0.30):
    for k in range(5):
        a, b = random.sample(pool, 2)
        segs, rttm, t = [], [], 0.0
        while t < 60:
            ra = random.choice(by_spk[a]); xa = rd(ra)
            segs.append(xa)
            rttm.append({"start": round(t, 3), "dur": round(len(xa) / SR, 3), "spk": a})
            ta = t; t += len(xa) / SR
            if random.random() < ratio * 2:   # 按比例插入重叠
                rb = random.choice(by_spk[b]); xb = rd(rb)
                ov = min(len(xb), int(len(xa) * ratio * 2))
                if ov > SR // 4:
                    start = max(0, len(segs[-1]) - ov)
                    segs[-1] = segs[-1].copy()
                    segs[-1][start:start + ov] += xb[:ov] * 0.9
                    rttm.append({"start": round(ta + start / SR, 3), "dur": round(ov / SR, 3),
                                 "spk": b, "overlap": True})
            sil = random.uniform(0.1, 0.3)
            segs.append(np.zeros(int(sil * SR))); t += sil
        y = np.concatenate(segs)
        cid = f"ovl{int(ratio*100):02d}_{k:02d}"
        wr(ddir / f"{cid}.wav", y)
        ov_sec = sum(s["dur"] for s in rttm if s.get("overlap"))
        meta_d.append({"id": cid, "target_overlap_ratio": ratio, "speakers": [a, b],
                       "duration_sec": round(len(y) / SR, 2),
                       "overlap_sec": round(ov_sec, 2),
                       "actual_overlap_ratio": round(ov_sec / (len(y) / SR), 4),
                       "segments": rttm})
(OUT / "overlap" / "meta.jsonl").write_text(
    "\n".join(json.dumps(m, ensure_ascii=False) for m in meta_d) + "\n", encoding="utf-8")
print(f"  {len(meta_d)} 条（10%/30% 重叠各 5 条，各约 60s）", flush=True)

# ================= E. 声纹试验对（复用既有音频） =================
print("E trials: 构造 same/diff 试验对 ...", flush=True)
same, diff = [], []
spk_ok = [s for s, v in by_spk.items() if len(v) >= 2]
for s in spk_ok:
    v = by_spk[s]
    for i in range(len(v)):
        for j in range(i + 1, len(v)):
            same.append((v[i], v[j]))
random.shuffle(same); same = same[:3000]
allr = sorted(have)
while len(diff) < len(same):
    x, y = random.sample(allr, 2)
    if sup[x]["speaker"] != sup[y]["speaker"]:
        diff.append((x, y))
trials = [{"a": a, "b": b, "target": 1} for a, b in same] + \
         [{"a": a, "b": b, "target": 0} for a, b in diff]
random.shuffle(trials)
(OUT / "trials.jsonl").write_text(
    "\n".join(json.dumps(t) for t in trials) + "\n", encoding="utf-8")
print(f"  {len(same)} 同人对 + {len(diff)} 异人对 = {len(trials)} 对", flush=True)

summary = {
    "generated": "2026-10-25",
    "sets": {
        "digits":   {"n": len(meta_a), "source": "macOS Tingting TTS（唯一可用中文发音人）",
                     "caveat": "合成语音，非真人；单一发音人；仅速率 170/200/230 变化。"
                               "用于考察数字串在解码/ITN 环节的行为，不能代表现场真人准确率。"},
        "longform": {"n": len(meta_b), "source": "AISHELL-3 同说话人真人音频拼接",
                     "caveat": "句间 0.35s 静音，非自然连续说话；无跨句上下文。"},
        "diar":     {"n": len(meta_c), "source": "AISHELL-3 多说话人交替拼接（真人）",
                     "caveat": "无自然抢话重叠，对应客户「轮流说话、极少抢话」描述；"
                               "录音条件同源，缺跨设备/跨房间差异。"},
        "overlap":  {"n": len(meta_d), "source": "AISHELL-3 两人叠加（真人）",
                     "caveat": "数字域叠加，无真实串音/混响。"},
        "trials":   {"n": len(trials), "source": "AISHELL-3 既有音频配对",
                     "caveat": "同语料同录音条件，跨域难度低于现场；平均时长 3.5s。"},
    },
}
(OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n完成 ->", OUT, flush=True)
