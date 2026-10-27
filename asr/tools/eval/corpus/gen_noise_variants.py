"""给 digits / longform 两个新集合生成噪声变体（复用与主实验相同的噪声与 SNR 定义）。"""
import json, os, random, math
from pathlib import Path
import numpy as np
import soundfile as sf

SP = Path(os.environ["SP"])
SR = 16000
random.seed(20261025); np.random.seed(20261025)

def speech_rms(x, sr=SR):
    fl = int(0.025 * sr); n = len(x) // fl
    if n == 0: return float(np.sqrt(np.mean(x ** 2) + 1e-12))
    f = x[:n*fl].reshape(n, fl); e = np.sqrt(np.mean(f**2, axis=1) + 1e-12)
    thr = max(e.max()*0.1, np.percentile(e, 60)*0.5); keep = e >= thr
    if not keep.any(): keep = e >= np.percentile(e, 50)
    return float(np.sqrt(np.mean(f[keep]**2) + 1e-12))

# 复刻主实验的 babble / traffic（同随机种子、同构造）
CLEAN = SP / "snrsets" / "clean"
sup_audio = {p.stem: p for p in CLEAN.glob("*.wav")}
import gzip
sup = {}
with gzip.open(Path(os.environ["CORPUS"]) / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz",
               "rt", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line); sup[d["recording_id"]] = d
by_spk = {}
for rid in sup_audio:
    by_spk.setdefault(sup[rid]["speaker"], []).append(rid)
for v in by_spk.values(): v.sort()
spks = sorted(by_spk); random.shuffle(spks)
need = int(60 * SR)
babble = np.zeros(need); used = 0
for s in spks:
    if used >= 20: break
    seg = np.concatenate([sf.read(str(sup_audio[r]), dtype="float64")[0] for r in by_spk[s]])
    if len(seg) < SR: continue
    t = np.tile(seg, int(np.ceil(need/len(seg))))[:need]
    babble += t / (speech_rms(t) + 1e-12); used += 1
babble /= (np.sqrt(np.mean(babble**2)) + 1e-12)
w = np.random.randn(need); W = np.fft.rfft(w)
fr = np.fft.rfftfreq(need, 1/SR)
shape = 1.0/np.sqrt(1.0 + (fr/180.0)**2); shape[fr < 20] = 0.0
traffic = np.fft.irfft(W*shape, n=need); traffic /= (np.sqrt(np.mean(traffic**2)) + 1e-12)
print(f"噪声复刻完成（babble 用 {used} 位说话人）", flush=True)

NOISE = {"babble": babble, "traffic": traffic}
LEVELS = [("quiet", 20.0), ("light", 15.0), ("medium", 7.0), ("heavy", 3.0)]

def mix(x, noise, snr_db):
    if len(noise) < len(x):
        noise = np.tile(noise, int(np.ceil(len(x)/len(noise))))
    off = random.randrange(0, len(noise) - len(x) + 1)
    n = noise[off:off+len(x)]
    s = speech_rms(x); nr = np.sqrt(np.mean(n**2)) + 1e-12
    return x + n * ((s / (10 ** (snr_db/20.0))) / nr)

for setname in ("digits", "longform"):
    src = SP / "gensets" / setname / "clean"
    files = sorted(src.glob("*.wav"))
    print(f"{setname}: {len(files)} 条 -> 8 个噪声变体", flush=True)
    for nk, nz in NOISE.items():
        for lk, snr in LEVELS:
            d = SP / "gensets" / setname / f"{nk}_{lk}"
            d.mkdir(parents=True, exist_ok=True)
            for p in files:
                x, sr = sf.read(str(p), dtype="float64"); assert sr == SR
                y = mix(x, nz, snr)
                m = np.max(np.abs(y))
                if m > 0.999: y = y * (0.999/m)
                sf.write(str(d / p.name), y.astype(np.float32), SR, subtype="PCM_16")
            print(f"  {nk}_{lk} 完成", flush=True)
print("完成", flush=True)
