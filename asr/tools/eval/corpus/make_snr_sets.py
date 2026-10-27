"""从 AISHELL-3 热词 500 条语料生成按 SNR 分层的测试集。

- 44.1k -> 16k：多相 windowed-sinc 重采样（无 scipy 依赖）
- 噪声两类：
  * babble  多人人声叠加（取自同语料其它说话人）—— 对应商圈/菜市场/人群密集
  * traffic 低频为主的合成噪声 —— 对应车内/主干道（合成，非实录，须标注）
- SNR 按有效语音段（能量门限之上）计算，避免静音拉高 SNR 估计
"""
import json, gzip, math, os, sys, random
from pathlib import Path
import numpy as np
import soundfile as sf

SRC = Path(os.environ["CORPUS"])
OUT = Path(os.environ["OUTDIR"])
SR_IN, SR_OUT = 44100, 16000
random.seed(20261025); np.random.seed(20261025)

# ---------- 多相 sinc 重采样 44100 -> 16000 ----------
UP, DOWN = 160, 441          # 16000/44100 = 160/441
K = 24                       # 单边窗宽（输入采样点）
FC = SR_OUT / SR_IN          # 归一化截止（防折叠）

def _kernels():
    ks = np.zeros((UP, 2 * K + 1), dtype=np.float64)
    idx = np.arange(-K, K + 1, dtype=np.float64)
    for ph in range(UP):
        frac = ph / UP
        x = idx - frac
        s = np.sinc(x * FC)
        w = 0.42 - 0.5 * np.cos(2 * np.pi * (x + K) / (2 * K)) + 0.08 * np.cos(4 * np.pi * (x + K) / (2 * K))
        h = s * w * FC
        ks[ph] = h / h.sum()
    return ks
KER = _kernels()

def resample_44k_to_16k(x: np.ndarray) -> np.ndarray:
    n_out = int(len(x) * SR_OUT / SR_IN)
    pos = np.arange(n_out, dtype=np.int64) * DOWN
    base = pos // UP
    phase = (pos % UP).astype(np.int64)
    xp = np.pad(x.astype(np.float64), (K, K + 2))
    out = np.zeros(n_out, dtype=np.float64)
    for ph in np.unique(phase):
        sel = np.nonzero(phase == ph)[0]
        b = base[sel]
        win = np.lib.stride_tricks.sliding_window_view(xp, 2 * K + 1)[b]
        out[sel] = win @ KER[ph]
    return out

# ---------- 有效语音 RMS（排除静音）----------
def speech_rms(x: np.ndarray, sr: int = SR_OUT) -> float:
    fl = int(0.025 * sr)
    n = len(x) // fl
    if n == 0:
        return float(np.sqrt(np.mean(x ** 2) + 1e-12))
    f = x[: n * fl].reshape(n, fl)
    e = np.sqrt(np.mean(f ** 2, axis=1) + 1e-12)
    thr = max(e.max() * 0.1, np.percentile(e, 60) * 0.5)
    keep = e >= thr
    if not keep.any():
        keep = e >= np.percentile(e, 50)
    return float(np.sqrt(np.mean(f[keep] ** 2) + 1e-12))

# ---------- 载入语料 ----------
sup = {}
with gzip.open(SRC / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        sup[d["recording_id"]] = d

items = []
for spk in sorted(os.listdir(SRC / "audio")):
    p = SRC / "audio" / spk
    if not p.is_dir():
        continue
    for w in sorted(os.listdir(p)):
        rid = Path(w).stem
        if rid in sup:
            items.append((rid, p / w))
print(f"语料条数 {len(items)}，标注条数 {len(sup)}", flush=True)

print("重采样 44.1k -> 16k ...", flush=True)
clean = {}
for i, (rid, path) in enumerate(items, 1):
    x, sr = sf.read(str(path), dtype="float64", always_2d=True)
    assert sr == SR_IN, (rid, sr)
    clean[rid] = resample_44k_to_16k(np.ascontiguousarray(x[:, 0]))
    if i % 100 == 0:
        print(f"  {i}/{len(items)}", flush=True)

# ---------- babble：20 条不同说话人叠加 ----------
by_spk = {}
for rid, _ in items:
    by_spk.setdefault(sup[rid]["speaker"], []).append(rid)
spks = sorted(by_spk)
random.shuffle(spks)
need = int(60 * SR_OUT)
babble = np.zeros(need)
used = 0
for spk in spks:
    if used >= 20:
        break
    seg = np.concatenate([clean[r] for r in by_spk[spk]])
    if len(seg) < SR_OUT:
        continue
    reps = int(np.ceil(need / len(seg)))
    t = np.tile(seg, reps)[:need]
    babble += t / (speech_rms(t) + 1e-12)
    used += 1
babble /= (np.sqrt(np.mean(babble ** 2)) + 1e-12)
print(f"babble 由 {used} 位说话人叠加，时长 {len(babble)/SR_OUT:.0f}s", flush=True)

# ---------- traffic：低频为主的合成噪声 ----------
w = np.random.randn(need)
W = np.fft.rfft(w)
fr = np.fft.rfftfreq(need, 1 / SR_OUT)
shape = 1.0 / np.sqrt(1.0 + (fr / 180.0) ** 2)      # ~-6dB/oct 以上滚降
shape[fr < 20] = 0.0
traffic = np.fft.irfft(W * shape, n=need)
traffic /= (np.sqrt(np.mean(traffic ** 2)) + 1e-12)

NOISE = {"babble": babble, "traffic": traffic}
# 客户 5 档：安静 >=20 / 轻度 10~20 / 中度 5~10 / 重度 0~5 / 极限 <0
LEVELS = [("quiet", 20.0), ("light", 15.0), ("medium", 7.0), ("heavy", 3.0), ("extreme", -5.0)]

def mix(x, noise, snr_db):
    if len(noise) < len(x):
        noise = np.tile(noise, int(np.ceil(len(x) / len(noise))))
    off = random.randrange(0, len(noise) - len(x) + 1)
    n = noise[off:off + len(x)]
    s_rms = speech_rms(x)
    n_rms = np.sqrt(np.mean(n ** 2)) + 1e-12
    target_n = s_rms / (10 ** (snr_db / 20.0))
    return x + n * (target_n / n_rms)

def write_set(name, fn):
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    peak_clip = 0
    for rid, _ in items:
        y = fn(clean[rid])
        m = np.max(np.abs(y))
        if m > 0.999:
            y = y * (0.999 / m); peak_clip += 1
        sf.write(str(d / f"{rid}.wav"), y.astype(np.float32), SR_OUT, subtype="PCM_16")
    print(f"  [{name}] 500 条写出，削峰缩放 {peak_clip} 条", flush=True)

OUT.mkdir(parents=True, exist_ok=True)
print("生成测试集 ...", flush=True)
write_set("clean", lambda x: x)
for nk, noise in NOISE.items():
    for lk, snr in LEVELS:
        write_set(f"{nk}_{lk}", (lambda nz, s: (lambda x: mix(x, nz, s)))(noise, snr))

meta = {
    "corpus": "aishell3_test_hotwords_500",
    "num_utterances": len(items),
    "sample_rate": SR_OUT,
    "resampler": "polyphase windowed-sinc 160/441, K=24, Blackman",
    "snr_definition": "有效语音段 RMS / 噪声 RMS（25ms 帧，能量门限排除静音）",
    "noise_types": {
        "babble": f"{used} 位同语料说话人叠加的多人人声（实录语音合成的 babble）",
        "traffic": "合成低频噪声（~180Hz 转折、-6dB/oct 滚降），车内/主干道代理，非实录",
    },
    "levels": {k: v for k, v in LEVELS},
    "sets": ["clean"] + [f"{n}_{l}" for n in NOISE for l, _ in LEVELS],
}
(OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
print("完成 ->", OUT, flush=True)
