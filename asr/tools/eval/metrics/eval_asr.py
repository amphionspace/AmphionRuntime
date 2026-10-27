"""COS 评测集统一评测器。

参考文本优先级：manifest.text（人工金标）> annotation.reference_candidate（机器/脚本参考）。
指标分三类：
  cer        字错率 / 字准确率（需要可信整句参考）
  term_hit   术语命中率 KWR —— 识别结果是否包含目标术语（labels.official_reference.term
             或 labels.target_terms；警言警语 V6 口径）
  plate_hit  车牌整串命中率 —— 从 labels.source_item_id 提取车牌号，检查是否完整出现
分组维度：labels.condition（噪声工况）、labels.accent（口音）、labels.scenario。
"""
import argparse, json, os, re, sys, time
from pathlib import Path
import numpy as np, soundfile as sf, sherpa_onnx
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_layout import transducer_paths


PUNCS = set(" \t\r\n,.!?;:'\"，。！？；：、《》（）()[]{}-—…·")
def nz(t): return "".join(c for c in (t or "") if c not in PUNCS)
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

PLATE = re.compile(r'([一-龥][A-Z][A-Z0-9]{4,6})')
def plate_of(row):
    sid = str(row.get("labels", {}).get("source_item_id", ""))
    m = PLATE.search(sid.replace("_", " "))
    if m: return m.group(1)
    ref = row.get("annotation", {}).get("reference_candidate") or ""
    m = PLATE.search(ref)
    return m.group(1) if m else None

def terms_of(row):
    lb = row.get("labels", {})
    out = []
    off = lb.get("official_reference") or {}
    if isinstance(off, dict) and off.get("term"): out.append(str(off["term"]))
    tt = lb.get("target_terms")
    if isinstance(tt, list): out += [str(x) for x in tt if x]
    elif isinstance(tt, str) and tt: out.append(tt)
    if not out:
        rc = row.get("annotation", {}).get("reference_candidate")
        if rc: out.append(str(rc))
    return [nz(x) for x in out if nz(x)]

ap = argparse.ArgumentParser()
ap.add_argument("--dataset", required=True)
ap.add_argument("--root", required=True)
ap.add_argument("--models", required=True)
ap.add_argument("--presets", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--hotwords", choices=["none", "pool", "pool+terms"], default="pool")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--sample", type=int, default=0, help="跨全集等距抽样 N 条，保持各标签分组覆盖")
ap.add_argument("--offset", type=int, default=0)
ap.add_argument("--tail", type=float, default=0.8)
a = ap.parse_args()

base = Path(a.root) / a.dataset
rows = [json.loads(l) for l in (base / "manifest.jsonl").open(encoding="utf-8")]
if a.offset: rows = rows[a.offset:]
if a.sample and a.sample < len(rows):
    step = len(rows) / a.sample
    rows = [rows[int(i*step)] for i in range(a.sample)]
if a.limit: rows = rows[:a.limit]
yaml = (base / "dataset.yaml").read_text(encoding="utf-8") if (base / "dataset.yaml").exists() else ""
status = (re.search(r'^annotation_status:\s*"?([^"\n]+)"?', yaml, re.M) or [None, "?"])[1]

presets = [l.strip() for l in Path(a.presets).read_text(encoding="utf-8").splitlines() if l.strip()]
pbuf = "\n".join(presets)
M = a.models
mp = transducer_paths(M)
r = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=mp["tokens"], encoder=mp["encoder"], decoder=mp["decoder"], joiner=mp["joiner"],
    num_threads=2, decoding_method="modified_beam_search",
    max_active_paths=8, hotwords_score=1.0, modeling_unit="bbpe", bpe_vocab=mp["bpe_vocab"])

def decode(x, hw):
    s = r.create_stream() if hw is None else r.create_stream(hw)
    s.accept_waveform(16000, x)
    s.accept_waveform(16000, np.zeros(int(16000*a.tail), dtype=np.float32))
    s.input_finished()
    while r.is_ready(s): r.decode_stream(s)
    return r.get_result(s)

groups = {}
recs = []
t0 = time.time()
skipped = 0
for i, row in enumerate(rows, 1):
    f = base / row["audio"]
    if not f.exists(): skipped += 1; continue
    x, sr = sf.read(str(f), dtype="float32")
    if sr != 16000: skipped += 1; continue
    if x.ndim > 1: x = x[:, 0]
    ref_gold = nz(row.get("text") or "")
    ref_cand = nz(row.get("annotation", {}).get("reference_candidate") or "")
    ref = ref_gold or ref_cand
    terms = terms_of(row)
    plate = plate_of(row)
    if a.hotwords == "none": hw = None
    elif a.hotwords == "pool": hw = pbuf
    else:
        extra = [f"{t} :3.0" for t in terms[:4] if t]
        hw = "\n".join(extra + presets)
    hyp = nz(decode(x, hw))
    lb = row.get("labels", {})
    keys = [("all", "all")]
    for dim in ("condition", "accent", "scenario"):
        v = lb.get(dim)
        if v: keys.append((dim, str(v)))
    for dim, v in keys:
        g = groups.setdefault((dim, v), dict(n=0, edits=0, reflen=0, term_hit=0, term_tot=0,
                                            plate_hit=0, plate_tot=0, exact=0, empty=0, audio=0.0))
        g["n"] += 1
        g["audio"] += len(x)/16000
        g["empty"] += int(not hyp)
        if ref:
            g["edits"] += ed(ref, hyp); g["reflen"] += len(ref)
            g["exact"] += int(hyp == ref)
        for t in terms:
            g["term_tot"] += 1; g["term_hit"] += int(t in hyp)
        if plate:
            g["plate_tot"] += 1; g["plate_hit"] += int(nz(plate) in hyp)
    recs.append({"id": row["id"], "ref": ref, "hyp": hyp, "terms": terms, "plate": plate,
                 "gold": bool(ref_gold), "labels": {k: lb.get(k) for k in ("condition","accent","scenario") if lb.get(k)}})
    if i % 100 == 0:
        print(f"[{a.dataset}] {i}/{len(rows)} {time.time()-t0:.0f}s", flush=True)

def pack(g):
    return {"n": g["n"],
            "cer": g["edits"]/g["reflen"] if g["reflen"] else None,
            "accuracy": 1-g["edits"]/g["reflen"] if g["reflen"] else None,
            "sentence_exact": g["exact"]/g["n"] if g["n"] else None,
            "term_hit_rate": g["term_hit"]/g["term_tot"] if g["term_tot"] else None,
            "term_total": g["term_tot"],
            "plate_hit_rate": g["plate_hit"]/g["plate_tot"] if g["plate_tot"] else None,
            "plate_total": g["plate_tot"],
            "empty": g["empty"], "audio_sec": round(g["audio"], 1)}
out = {"dataset": a.dataset, "annotation_status": status, "hotwords": a.hotwords,
       "n_manifest": len(rows), "skipped": skipped,
       "groups": {f"{d}={v}": pack(g) for (d, v), g in sorted(groups.items())}}
op = Path(a.out); op.parent.mkdir(parents=True, exist_ok=True)
op.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in recs) + "\n", encoding="utf-8")
Path(str(op).replace(".jsonl", ".summary.json")).write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
A = out["groups"].get("all=all", {})
print(f"[{a.dataset}] 完成 {A.get('n')} 条 ({A.get('audio_sec')}s) {time.time()-t0:.0f}s  标注={status}  热词={a.hotwords}")
for k in ("accuracy", "sentence_exact", "term_hit_rate", "plate_hit_rate"):
    if A.get(k) is not None:
        print(f"    {k:<16} {A[k]*100:6.2f}%" + (f"  (n={A['term_total']})" if k=="term_hit_rate"
              else f"  (n={A['plate_total']})" if k=="plate_hit_rate" else ""))
