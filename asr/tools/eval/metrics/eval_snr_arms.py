"""按 SNR 分层评测端侧 ASR 与热词指标。

评分口径完全沿用 asr/tools/hotwords/01_eval_aishell3_hotwords.py：
  normalize_zh 去标点 -> 字符编辑距离 CER -> 热词精确命中（子串）。

四个臂：
  greedy_nohw   greedy，无任何热词                          —— 通用 ASR 下限
  pool_nohw     mbs8 + 370 预置警务热词@全局1.0，无用户热词  —— 出厂默认（通用语音）
  pool_oracle3  上者 + 该条 oracle 热词@3.0                  —— 出厂默认（配了热词）
  oracle3_only  仅 oracle 热词，全局 3.0                     —— 与已发布 96.12% 同口径
"""
import argparse, gzip, json, os, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf
import sherpa_onnx

PUNCS = set(" \t\r\n,.!?;:'\"，。！？；：、《》（）()[]{}-—…")

def normalize_zh(t): return "".join(c for c in t if c not in PUNCS)

def edit_distance(a, b):
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]

def build(models, method, score, presets_file=None):
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=f"{models}/tokens.txt", encoder=f"{models}/encoder.int8.ort",
        decoder=f"{models}/decoder.ort", joiner=f"{models}/joiner.int8.ort",
        num_threads=2, decoding_method=method, max_active_paths=8,
        hotwords_score=score, modeling_unit="bbpe", bpe_vocab=f"{models}/bbpe.vocab",
    )

def decode(r, x, hotwords=None, tail=0.5):
    s = r.create_stream() if hotwords is None else r.create_stream(hotwords)
    s.accept_waveform(16000, x)
    if tail > 0:
        s.accept_waveform(16000, np.zeros(int(16000 * tail), dtype=np.float32))
    s.input_finished()
    while r.is_ready(s):
        r.decode_stream(s)
    return r.get_result(s)

ap = argparse.ArgumentParser()
ap.add_argument("--set", required=True)
ap.add_argument("--sets-dir", required=True)
ap.add_argument("--corpus", required=True)
ap.add_argument("--models", required=True)
ap.add_argument("--presets", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--arms", nargs="+", required=True)
a = ap.parse_args()

sup = {}
with gzip.open(Path(a.corpus) / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz",
               "rt", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        hw = [str(w) for w in (d.get("custom", {}).get("hotwords") or []) if str(w).strip()]
        if hw:
            sup[d["recording_id"]] = (d.get("text") or "", hw)

presets = [l.strip() for l in Path(a.presets).read_text(encoding="utf-8").splitlines() if l.strip()]
preset_buf = "\n".join(presets)

recs = {}
if "greedy_nohw" in a.arms:  recs["greedy_nohw"] = build(a.models, "greedy_search", 1.0)
if {"pool_nohw", "pool_oracle3"} & set(a.arms):
    shared = build(a.models, "modified_beam_search", 1.0)
    for k in ("pool_nohw", "pool_oracle3"):
        if k in a.arms: recs[k] = shared
if "oracle3_only" in a.arms: recs["oracle3_only"] = build(a.models, "modified_beam_search", 3.0)

sdir = Path(a.sets_dir) / a.set
ids = sorted(p.stem for p in sdir.glob("*.wav") if p.stem in sup)
agg = {k: dict(edits=0, reflen=0, hw_hit=0, hw_tot=0, all_hit=0, n=0, empty=0, sec=0.0, audio=0.0)
       for k in a.arms}
outp = Path(a.out); outp.parent.mkdir(parents=True, exist_ok=True)
t_start = time.time()
with outp.open("w", encoding="utf-8") as fout:
    for i, rid in enumerate(ids, 1):
        ref, hw = sup[rid]
        x, sr = sf.read(str(sdir / f"{rid}.wav"), dtype="float32")
        assert sr == 16000
        row = {"id": rid, "ref": ref, "hotwords": hw, "set": a.set}
        for arm in a.arms:
            if arm == "greedy_nohw":     hwbuf = None
            elif arm == "pool_nohw":     hwbuf = preset_buf
            elif arm == "pool_oracle3":  hwbuf = "\n".join([f"{w} :3.0" for w in hw] + presets)
            elif arm == "oracle3_only":  hwbuf = "\n".join(hw)
            else: raise SystemExit(arm)
            t0 = time.time()
            hyp = decode(recs[arm], x, hwbuf)
            dt = time.time() - t0
            rn, hn = normalize_zh(ref), normalize_zh(hyp)
            hwn = [normalize_zh(w) for w in hw if normalize_zh(w)]
            hits = [w for w in hwn if w in hn]
            g = agg[arm]
            g["edits"] += edit_distance(rn, hn); g["reflen"] += len(rn)
            g["hw_hit"] += len(hits); g["hw_tot"] += len(hwn)
            g["all_hit"] += int(len(hits) == len(hwn) and bool(hwn))
            g["n"] += 1; g["empty"] += int(not hn)
            g["sec"] += dt; g["audio"] += len(x) / 16000
            row[arm] = {"hyp": hyp, "cer_edits": edit_distance(rn, hn), "ref_len": len(rn),
                        "hw_hits": len(hits), "hw_count": len(hwn)}
        fout.write(json.dumps(row, ensure_ascii=False) + "\n")
        if i % 100 == 0:
            print(f"[{a.set}] {i}/{len(ids)} {time.time()-t_start:.0f}s", flush=True)

summary = {"set": a.set, "n": len(ids), "arms": {}}
for arm, g in agg.items():
    summary["arms"][arm] = {
        "cer": g["edits"] / g["reflen"] if g["reflen"] else None,
        "accuracy": 1 - g["edits"] / g["reflen"] if g["reflen"] else None,
        "hotword_exact_recall": g["hw_hit"] / g["hw_tot"] if g["hw_tot"] else None,
        "sample_all_hotword_hit": g["all_hit"] / g["n"] if g["n"] else None,
        "empty_outputs": g["empty"], "n": g["n"],
        "rtf": g["sec"] / g["audio"] if g["audio"] else None,
    }
Path(str(outp).replace(".jsonl", ".summary.json")).write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[{a.set}] 完成 {len(ids)} 条，用时 {time.time()-t_start:.0f}s", flush=True)
for arm, m in summary["arms"].items():
    print(f"   {arm:<14} 准确率 {m['accuracy']*100:6.2f}%  热词召回 "
          f"{(m['hotword_exact_recall'] or 0)*100:6.2f}%  空输出 {m['empty_outputs']}", flush=True)
