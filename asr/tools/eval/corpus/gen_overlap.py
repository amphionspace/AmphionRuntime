"""重叠讲话测试集（受控重叠度）。

重叠度定义（本测试采用，需与客户确认）：
    overlap_ratio = 重叠语音时长 / 机主(target)语音总时长
机主 = 被识别/被声纹确认的目标说话人；干扰人叠加在机主语音之上。

每条产出：
  mix.wav     机主 + 干扰人 混合（被测音频）
  target.wav  仅机主（用于 oracle 对照）
  enroll.wav  机主的另一条音频（声纹注册用，与 mix 中内容不重复）
  meta        机主文本、重叠区间、实测重叠度
"""
import gzip, json, os, random
from pathlib import Path
import numpy as np, soundfile as sf

SP = Path(os.environ["SP"]); CORPUS = Path(os.environ["CORPUS"])
SR = 16000
random.seed(20261026); np.random.seed(20261026)
OUT = SP / "gensets" / "overlap2"

sup = {}
with gzip.open(CORPUS / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz",
               "rt", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line); sup[d["recording_id"]] = d
CLEAN = SP / "snrsets" / "clean"
have = {p.stem: p for p in CLEAN.glob("*.wav")}
by_spk = {}
for rid in have:
    by_spk.setdefault(sup[rid]["speaker"], []).append(rid)
for v in by_spk.values(): v.sort()
pool = [s for s, v in by_spk.items() if len(v) >= 7]
print(f"可用说话人 {len(pool)}（每人 >=7 条）", flush=True)

def rd(rid):
    x, _ = sf.read(str(have[rid]), dtype="float64"); return x

def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-12))

items = []
RATIOS = [0.10, 0.30]
PER = 8
for ratio in RATIOS:
    for k in range(PER):
        tgt, itf = random.sample(pool, 2)
        trids = by_spk[tgt][:]; random.shuffle(trids)
        enroll_rid = trids.pop()                      # 注册用，不进 mix
        # 机主时间线
        segs, texts, spans, t = [], [], [], 0.0
        for rid in trids:
            x = rd(rid)
            segs.append(x); spans.append((t, t + len(x) / SR))
            texts.append((sup[rid]["text"] or "").strip())
            t += len(x) / SR
            gap = random.uniform(0.15, 0.35)
            segs.append(np.zeros(int(gap * SR))); t += gap
            if t >= 55: break
        target = np.concatenate(segs)
        speech_sec = sum(b - a for a, b in spans)
        need_ov = speech_sec * ratio
        # 叠加干扰人，直到达到目标重叠度
        mix = target.copy()
        irids = by_spk[itf][:]; random.shuffle(irids)
        ov_regions, got = [], 0.0
        gi = 0
        while got < need_ov and gi < len(irids) * 4:
            ix = rd(irids[gi % len(irids)]); gi += 1
            a, b = random.choice(spans)
            seg_len = b - a
            dur = min(len(ix) / SR, seg_len * 0.9, need_ov - got + 0.3)
            if dur < 0.4: continue
            start = a + random.uniform(0, max(0.0, seg_len - dur))
            i0 = int(start * SR); n = int(dur * SR)
            if i0 + n > len(mix): continue
            # 干扰人电平与机主相当（0 dB TMR），这是重叠场景的保守设定
            seg = ix[:n]
            seg = seg * (rms(target[i0:i0 + n]) / (rms(seg) + 1e-12))
            mix[i0:i0 + n] += seg
            ov_regions.append((round(start, 3), round(start + dur, 3)))
            got += dur
        cid = f"ov{int(ratio*100):02d}_{k:02d}"
        for name, arr in (("mix", mix), ("target", target), ("enroll", rd(enroll_rid))):
            d = OUT / name / "clean"; d.mkdir(parents=True, exist_ok=True)
            y = arr.copy(); m = np.max(np.abs(y))
            if m > 0.999: y = y * (0.999 / m)
            sf.write(str(d / f"{cid}.wav"), y.astype(np.float32), SR, subtype="PCM_16")
        items.append({"id": cid, "target_speaker": tgt, "interferer": itf,
                      "target_ratio": ratio, "enroll_rid": enroll_rid,
                      "duration_sec": round(len(mix) / SR, 2),
                      "target_speech_sec": round(speech_sec, 2),
                      "overlap_sec": round(got, 2),
                      "actual_overlap_ratio": round(got / speech_sec, 4),
                      "overlap_regions": ov_regions,
                      "text": "".join(texts)})
        print(f"  {cid} 机主={tgt} 干扰={itf} 目标重叠 {ratio:.0%} -> 实测 {got/speech_sec:.1%}"
              f"  时长 {len(mix)/SR:.1f}s", flush=True)

(OUT / "meta.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items) + "\n",
                                encoding="utf-8")

# 噪声变体（仅 mix，供分噪声档评测）
def speech_rms(x, sr=SR):
    fl = int(0.025 * sr); n = len(x) // fl
    if n == 0: return rms(x)
    f = x[:n*fl].reshape(n, fl); e = np.sqrt(np.mean(f**2, axis=1) + 1e-12)
    thr = max(e.max()*0.1, np.percentile(e, 60)*0.5); keep = e >= thr
    if not keep.any(): keep = e >= np.percentile(e, 50)
    return float(np.sqrt(np.mean(f[keep]**2) + 1e-12))

spks = sorted(by_spk); random.shuffle(spks)
need = int(60 * SR); babble = np.zeros(need); used = 0
for s in spks:
    if used >= 20: break
    seg = np.concatenate([rd(r) for r in by_spk[s]])
    if len(seg) < SR: continue
    tt = np.tile(seg, int(np.ceil(need/len(seg))))[:need]
    babble += tt / (speech_rms(tt) + 1e-12); used += 1
babble /= (rms(babble) + 1e-12)
w = np.random.randn(need); W = np.fft.rfft(w); fr = np.fft.rfftfreq(need, 1/SR)
shape = 1.0/np.sqrt(1.0 + (fr/180.0)**2); shape[fr < 20] = 0.0
traffic = np.fft.irfft(W*shape, n=need); traffic /= (rms(traffic) + 1e-12)
LEVELS = [("quiet", 20.0), ("light", 15.0), ("medium", 7.0), ("heavy", 3.0)]
src = OUT / "mix" / "clean"
for nk, nz in (("babble", babble), ("traffic", traffic)):
    for lk, snr in LEVELS:
        d = OUT / "mix" / f"{nk}_{lk}"; d.mkdir(parents=True, exist_ok=True)
        for p in sorted(src.glob("*.wav")):
            x, _ = sf.read(str(p), dtype="float64")
            nn = np.tile(nz, int(np.ceil(len(x)/len(nz))))[:len(x)]
            s = speech_rms(x)
            y = x + nn * ((s / (10 ** (snr/20.0))) / (rms(nn) + 1e-12))
            m = np.max(np.abs(y))
            if m > 0.999: y = y * (0.999/m)
            sf.write(str(d / p.name), y.astype(np.float32), SR, subtype="PCM_16")
        print(f"  mix/{nk}_{lk} 完成", flush=True)

ar = [x["actual_overlap_ratio"] for x in items]
print(f"\n完成 {len(items)} 条；实测重叠度 10% 组 "
      f"{np.mean([x['actual_overlap_ratio'] for x in items if x['target_ratio']==0.10]):.1%}，"
      f"30% 组 {np.mean([x['actual_overlap_ratio'] for x in items if x['target_ratio']==0.30]):.1%}", flush=True)
