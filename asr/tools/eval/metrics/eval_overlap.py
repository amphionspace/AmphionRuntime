"""重叠场景：机主 ASR 准确率 + 机主声纹识别准确率。

机主 ASR：对混合音频解码，与机主参考文本算 CER（客户看到的就是这个）。
          同时跑 target.wav（仅机主）作 oracle 上界，差值即重叠造成的损失。
机主声纹：注册 = 机主另一条干净音频；测试 = 混合音频的重叠区间片段。
          正例 = 该机主注册 vs 自己的重叠片段；负例 = 其他说话人注册 vs 该重叠片段。
"""
import json, os, sys
from pathlib import Path
import numpy as np, soundfile as sf, sherpa_onnx

SP = Path(os.environ["SP"]); M = os.environ["MODELS"]; VP = os.environ["VP_MODEL"]
VAR = os.environ.get("OV_SET", "clean")
base = SP / "gensets" / "overlap2"
meta = [json.loads(l) for l in (base / "meta.jsonl").open(encoding="utf-8")]
presets = [l.strip() for l in (SP / "hw_full_nouser.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
pbuf = "\n".join(presets)
PUNCS = set(" \t\r\n,.!?;:'\"，。！？；：、《》（）()[]{}-—…")
def nz(t): return "".join(c for c in t if c not in PUNCS)
def ed(a, b):
    if not a: return len(b)
    if not b: return len(a)
    p = list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        c = [i] + [0]*len(b)
        for j, cb in enumerate(b, 1):
            c[j] = min(p[j]+1, c[j-1]+1, p[j-1]+(ca != cb))
        p = c
    return p[-1]

r = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=f"{M}/tokens.txt", encoder=f"{M}/encoder.int8.ort", decoder=f"{M}/decoder.ort",
    joiner=f"{M}/joiner.int8.ort", num_threads=4, decoding_method="modified_beam_search",
    max_active_paths=8, hotwords_score=1.0, modeling_unit="bbpe", bpe_vocab=f"{M}/bbpe.vocab")
def dec(path):
    x, sr = sf.read(str(path), dtype="float32")
    s = r.create_stream(pbuf); s.accept_waveform(16000, x)
    s.accept_waveform(16000, np.zeros(16000, dtype=np.float32)); s.input_finished()
    while r.is_ready(s): r.decode_stream(s)
    return r.get_result(s)

ex = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=VP, num_threads=4))
def emb(x, sr=16000):
    s = ex.create_stream(); s.accept_waveform(sr, x.astype(np.float32)); s.input_finished()
    v = np.asarray(ex.compute(s), dtype=np.float64)
    return v / (np.linalg.norm(v) + 1e-12)

rows = []
for m in meta:
    cid = m["id"]
    mixp = base / "mix" / VAR / f"{cid}.wav"
    if not mixp.exists(): continue
    ref = nz(m["text"])
    hyp_mix = nz(dec(mixp))
    hyp_tgt = nz(dec(base / "target" / "clean" / f"{cid}.wav"))
    rows.append({"id": cid, "ratio": m["target_ratio"], "actual": m["actual_overlap_ratio"],
                 "reflen": len(ref), "ed_mix": ed(ref, hyp_mix), "ed_tgt": ed(ref, hyp_tgt),
                 "hyp_mix": hyp_mix[:80]})

# 声纹：注册 vs 重叠片段
enr, tst = {}, {}
for m in meta:
    cid = m["id"]
    mixp = base / "mix" / VAR / f"{cid}.wav"
    if not mixp.exists(): continue
    e, _ = sf.read(str(base / "enroll" / "clean" / f"{cid}.wav"), dtype="float64")
    enr[cid] = emb(e)
    x, _ = sf.read(str(mixp), dtype="float64")
    segs = [x[int(a*16000):int(b*16000)] for a, b in m["overlap_regions"]
            if (b - a) >= 0.5 and int(b*16000) <= len(x)]
    if segs:
        tst[cid] = [emb(s) for s in segs]

pos, neg = [], []
cids = sorted(tst)
for cid in cids:
    for v in tst[cid]:
        pos.append(float(enr[cid] @ v))
        for other in cids:
            if other != cid:
                neg.append(float(enr[other] @ v))
scores = np.array(pos + neg); labels = np.array([1]*len(pos) + [0]*len(neg))
o = np.argsort(-scores); ls = labels[o]; ss = scores[o]
P, N = int(labels.sum()), int((1-labels).sum())
tp = np.cumsum(ls); fp = np.cumsum(1-ls)
frr = 1 - tp/P; far = fp/N
i = int(np.argmin(np.abs(far-frr))); eer = float((far[i]+frr[i])/2)

agg_asr = {}
for ratio in (0.10, 0.30):
    g = [x for x in rows if x["ratio"] == ratio]
    if not g: continue
    rl = sum(x["reflen"] for x in g)
    agg_asr[f"{int(ratio*100)}%"] = {
        "n": len(g), "actual_overlap": round(float(np.mean([x["actual"] for x in g]))*100, 2),
        "cer_mix": round(sum(x["ed_mix"] for x in g)/rl*100, 2),
        "accuracy_mix": round(100 - sum(x["ed_mix"] for x in g)/rl*100, 2),
        "cer_target_only": round(sum(x["ed_tgt"] for x in g)/rl*100, 2),
        "accuracy_target_only": round(100 - sum(x["ed_tgt"] for x in g)/rl*100, 2),
    }
out = {"variant": VAR, "asr": agg_asr,
       "voiceprint": {"eer": round(eer*100, 2), "accuracy_at_eer": round((1-eer)*100, 2),
                      "num_pos": P, "num_neg": N}}
(SP / "evalout" / f"ov_{VAR}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[{VAR}] 机主 ASR")
for k, v in agg_asr.items():
    print(f"  重叠 {k}（实测 {v['actual_overlap']}%）: 混合 {v['accuracy_mix']}%  "
          f"| 仅机主 oracle {v['accuracy_target_only']}%  | 重叠损失 "
          f"{v['accuracy_target_only']-v['accuracy_mix']:.2f}pp")
print(f"[{VAR}] 机主声纹（注册 vs 重叠片段）EER {eer*100:.2f}% -> 准确率 {(1-eer)*100:.2f}%"
      f"  (正例 {P} / 负例 {N})")
