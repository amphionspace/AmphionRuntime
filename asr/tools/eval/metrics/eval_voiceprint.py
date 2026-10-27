"""声纹 EER 实测：用生产 ERes2Net 模型 + cosine 打分（与 SDK 同 backend）。"""
import json, os, sys
from pathlib import Path
import numpy as np
import soundfile as sf
import sherpa_onnx

SP = Path(os.environ["SP"])
MODEL = os.environ["VP_MODEL"]
CLEAN = SP / "snrsets" / "clean"
NOISE_SET = os.environ.get("VP_SET", "clean")
AUDIO = SP / "snrsets" / NOISE_SET

cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=4, debug=False)
ex = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
print(f"ERes2Net 加载完成，embedding 维度 {ex.dim}", flush=True)

trials = [json.loads(l) for l in (SP / "gensets" / "trials.jsonl").open(encoding="utf-8")]
need = sorted({t["a"] for t in trials} | {t["b"] for t in trials})
emb = {}
for i, rid in enumerate(need, 1):
    x, sr = sf.read(str(AUDIO / f"{rid}.wav"), dtype="float32")
    s = ex.create_stream(); s.accept_waveform(sr, x); s.input_finished()
    v = np.asarray(ex.compute(s), dtype=np.float64)
    emb[rid] = v / (np.linalg.norm(v) + 1e-12)
    if i % 100 == 0:
        print(f"  embedding {i}/{len(need)}", flush=True)

scores = np.array([float(emb[t["a"]] @ emb[t["b"]]) for t in trials])
labels = np.array([t["target"] for t in trials])

# EER
order = np.argsort(-scores)
s_sorted, l_sorted = scores[order], labels[order]
P, N = int(labels.sum()), int((1 - labels).sum())
tp = np.cumsum(l_sorted); fp = np.cumsum(1 - l_sorted)
frr = 1 - tp / P            # 漏接受（同人被拒）
far = fp / N                # 误接受（异人被接）
i = int(np.argmin(np.abs(far - frr)))
eer = float((far[i] + frr[i]) / 2); thr = float(s_sorted[i])

def frr_at_far(target):
    j = np.searchsorted(far, target, side="right") - 1
    j = max(j, 0)
    return float(frr[j]), float(s_sorted[j])

out = {
    "set": NOISE_SET, "num_trials": len(trials), "num_same": P, "num_diff": N,
    "eer": eer, "eer_threshold": thr,
    "accuracy_at_eer": 1 - eer,
    "frr_at_far_1pct": frr_at_far(0.01), "frr_at_far_0.1pct": frr_at_far(0.001),
    "sdk_threshold_note": "SDK 用 segment-level cosine 门控，与此处同 backend",
}
(SP / "evalout" / f"vp_{NOISE_SET}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[{NOISE_SET}] 试验对 {len(trials)}（同人 {P} / 异人 {N}）")
print(f"  EER = {eer*100:.2f}%  (阈值 {thr:.4f})  -> EER 工作点准确率 {(1-eer)*100:.2f}%")
f1, t1 = out["frr_at_far_1pct"]; f01, t01 = out["frr_at_far_0.1pct"]
print(f"  FAR=1%   时 FRR = {f1*100:.2f}%  (阈值 {t1:.4f})")
print(f"  FAR=0.1% 时 FRR = {f01*100:.2f}%  (阈值 {t01:.4f})")
