"""对已有解码结果补 ITN 再评分。

生产 SDK 在 final 文本上应用 ITN（中文数字 -> 阿拉伯数字），而宿主 CLI 未启用，
导致与「阿拉伯数字参考」对不上。这里用从生产源码原样抽出的 itn_probe
（CanonicalizeAmbiguousDigitOne + CollapseSpokenDigitRuns，wetext_processor.cc 第 19-250 行）
对假设文本做同样变换后重新计分。

注意：itn_probe 只含数字串折叠这一段，不含 Tag/Verbalize 的 FST 全量 ITN，
因此对日期/单位等其它 ITN 规则不生效 —— 对车牌/身份证/手机号这类裸数字串是对位的。
"""
import json, os, subprocess, sys, glob, re
from pathlib import Path

SP = Path(os.environ["SP"])
PROBE = os.environ.get("ITN_PROBE", str(SP / "itn_probe"))
DEC = Path(os.environ.get("DECODE_DIR", str(SP / "decodeout")))
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

def itn_batch(texts):
    """一次性把所有假设过 ITN 探针。"""
    inp = "\n".join(t.replace("\n", " ") or "." for t in texts) + "\n"
    out = subprocess.run([PROBE], input=inp, capture_output=True, text=True).stdout
    res = []
    for blk in out.split("IN       : ")[1:]:
        m = re.search(r"COLLAPSED: (.*)", blk)
        res.append(m.group(1) if m else "")
    if len(res) != len(texts):
        raise SystemExit(f"ITN 输出条数不符: {len(res)} vs {len(texts)}")
    return res

report = []
for jf in sorted(glob.glob(str(DEC / "*.jsonl"))):
    tag = Path(jf).stem
    rows = [json.loads(l) for l in open(jf, encoding="utf-8")]
    if not rows: continue
    hyps = [r["hyp"] for r in rows]
    refs = [r["ref"] for r in rows]
    try:
        # 两侧同时归一化：参考文本的数字写法在各数据集间不统一
        # （车牌集用阿拉伯数字，真人集用中文数字），只改一侧会造成系统性错配。
        itn = itn_batch(hyps)
        itn_ref = itn_batch(refs)
    except SystemExit as e:
        print(f"[skip] {tag}: {e}"); continue
    g = dict(n=0, edits=0, reflen=0, exact=0, th=0, tt=0, ph=0, pt=0)
    g0 = dict(edits=0, reflen=0, exact=0, th=0, tt=0, ph=0, pt=0)
    for r, h2, rf2 in zip(rows, itn, itn_ref):
        h2 = nz(h2); h1 = nz(r["hyp"]); ref = nz(rf2)
        g["n"] += 1
        if ref:
            g["edits"] += ed(ref, h2); g["reflen"] += len(ref); g["exact"] += int(h2 == ref)
            ref0 = nz(r["ref"])
            g0["edits"] += ed(ref0, h1); g0["reflen"] += len(ref0); g0["exact"] += int(h1 == ref0)
        terms_n = itn_batch(r.get("terms") or []) if r.get("terms") else []
        for t in terms_n:
            t = nz(t); g["tt"] += 1; g0["tt"] += 1
            g["th"] += int(t in h2); g0["th"] += int(t in h1)
        if r.get("plate"):
            p = nz(r["plate"]); g["pt"] += 1; g0["pt"] += 1
            g["ph"] += int(p in h2); g0["ph"] += int(p in h1)
    def pk(x):
        return {"accuracy": (1 - x["edits"]/x["reflen"]) if x["reflen"] else None,
                "sentence_exact": (x["exact"]/g["n"]) if g["n"] else None,
                "term_hit_rate": (x["th"]/x["tt"]) if x["tt"] else None,
                "plate_hit_rate": (x["ph"]/x["pt"]) if x["pt"] else None}
    rec = {"tag": tag, "n": g["n"], "with_itn": pk(g), "no_itn": pk(g0),
           "term_total": g["tt"], "plate_total": g["pt"]}
    report.append(rec)
    (DEC / f"{tag}.itn.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"{'tag':<16}{'条数':>5}  {'字准确率(ITN前→后)':<24}{'整句全对':<20}{'术语KWR':<20}{'车牌命中'}")
print("-"*110)
def fmt(a, b):
    f = lambda v: "   —  " if v is None else f"{v*100:6.2f}%"
    return f"{f(a)}→{f(b)}"
for r in report:
    w, o = r["with_itn"], r["no_itn"]
    print(f"{r['tag']:<16}{r['n']:>5}  {fmt(o['accuracy'],w['accuracy']):<24}"
          f"{fmt(o['sentence_exact'],w['sentence_exact']):<20}"
          f"{fmt(o['term_hit_rate'],w['term_hit_rate']):<20}"
          f"{fmt(o['plate_hit_rate'],w['plate_hit_rate'])}")
(DEC / "RESCORE_ITN.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
