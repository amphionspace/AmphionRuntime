"""数字串（车牌/身份证/手机号/计数）与长语音的 ASR 评测。

数字集额外统计「数字串整串正确率」—— 客户关心的是整个号码对不对，
单字 CER 会掩盖「11 位里错 1 位」这种业务上完全不可用的情况。
"""
import argparse, json, os, re, time
from pathlib import Path
import numpy as np, soundfile as sf, sherpa_onnx

PUNCS = set(" \t\r\n,.!?;:'\"，。！？；：、《》（）()[]{}-—…")
def nz(t): return "".join(c for c in t if c not in PUNCS)
def ed(a, b):
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0]*len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j]+1, cur[j-1]+1, prev[j-1]+(ca != cb))
        prev = cur
    return prev[-1]

DIG = set("零〇一二三四五六七八九十幺两")
def digit_runs(t):
    return [r for r in re.findall(r"[" + "".join(DIG) + r"]+", t) if len(r) >= 3]

ap = argparse.ArgumentParser()
ap.add_argument("--set", required=True)
ap.add_argument("--variant", required=True)
ap.add_argument("--models", required=True)
ap.add_argument("--presets", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--tail", type=float, default=1.0)
a = ap.parse_args()

SP = Path(os.environ["SP"])
base = SP / "gensets" / a.set
meta = {json.loads(l)["id"]: json.loads(l) for l in (base / "meta.jsonl").open(encoding="utf-8")}
adir = base / a.variant

presets = [l.strip() for l in Path(a.presets).read_text(encoding="utf-8").splitlines() if l.strip()]
pbuf = "\n".join(presets)
M = a.models
r = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=f"{M}/tokens.txt", encoder=f"{M}/encoder.int8.ort", decoder=f"{M}/decoder.ort",
    joiner=f"{M}/joiner.int8.ort", num_threads=2, decoding_method="modified_beam_search",
    max_active_paths=8, hotwords_score=1.0, modeling_unit="bbpe", bpe_vocab=f"{M}/bbpe.vocab")

def dec(x, hw):
    s = r.create_stream() if hw is None else r.create_stream(hw)
    s.accept_waveform(16000, x)
    s.accept_waveform(16000, np.zeros(int(16000*a.tail), dtype=np.float32))
    s.input_finished()
    while r.is_ready(s): r.decode_stream(s)
    return r.get_result(s)

agg = {}
rows = []
t0 = time.time()
for i, (cid, m) in enumerate(sorted(meta.items()), 1):
    f = adir / f"{cid}.wav"
    if not f.exists(): continue
    x, sr = sf.read(str(f), dtype="float32"); assert sr == 16000
    ref = nz(m["text"])
    kind = m.get("kind", a.set)
    row = {"id": cid, "kind": kind, "ref": m["text"]}
    for arm, hw in (("pool_nohw", pbuf),):
        hyp = nz(dec(x, hw))
        e = ed(ref, hyp)
        g = agg.setdefault((kind, arm), dict(edits=0, reflen=0, n=0, run_ok=0, run_tot=0, exact=0))
        g["edits"] += e; g["reflen"] += len(ref); g["n"] += 1
        g["exact"] += int(hyp == ref)
        for run in digit_runs(ref):
            g["run_tot"] += 1
            g["run_ok"] += int(run in hyp)
        row[arm] = {"hyp": hyp, "edits": e, "reflen": len(ref)}
    rows.append(row)
    if i % 50 == 0: print(f"[{a.set}/{a.variant}] {i}/{len(meta)} {time.time()-t0:.0f}s", flush=True)

out = {"set": a.set, "variant": a.variant, "by_kind": {}}
for (kind, arm), g in agg.items():
    out["by_kind"][f"{kind}|{arm}"] = {
        "n": g["n"], "cer": g["edits"]/g["reflen"] if g["reflen"] else None,
        "accuracy": 1-g["edits"]/g["reflen"] if g["reflen"] else None,
        "sentence_exact": g["exact"]/g["n"] if g["n"] else None,
        "digit_run_exact": g["run_ok"]/g["run_tot"] if g["run_tot"] else None,
        "digit_runs": g["run_tot"],
    }
op = Path(a.out); op.parent.mkdir(parents=True, exist_ok=True)
op.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
Path(str(op).replace(".jsonl", ".summary.json")).write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[{a.set}/{a.variant}] 完成 {len(rows)} 条 {time.time()-t0:.0f}s", flush=True)
for k, v in sorted(out["by_kind"].items()):
    print(f"   {k:<22} n={v['n']:<4} 准确率 {v['accuracy']*100:6.2f}%  整句正确 "
          f"{v['sentence_exact']*100:6.2f}%  数字串整串正确 "
          f"{(v['digit_run_exact'] or 0)*100:6.2f}% ({v['digit_runs']})", flush=True)
