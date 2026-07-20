#!/usr/bin/env python3
# (b) Test deleting segmentation-hijacking lexicon entries. Caches native-TN output
# for the regression sets once, then re-scores G2P under different purge sets so we
# can pick a zero-regression, net-positive deletion set fast.
import json, re, os, sys, subprocess
sys.path.insert(0, os.path.dirname(__file__))
import frontend, g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
ZH = os.environ.get("ZH_TTS") or os.path.join(os.path.dirname(__file__), "..", "..", "..", "dingqiao_lits", "build", "host-tn", "zh_tts")
B = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/"
POLY = B + "高频多音字复杂句子语料500条-逐句独立版.jsonl"
REG = [("round15", B + "pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl"),
       ("hard500", B + "github-tts-hardcases-500.jsonl"),
       ("addl500", B + "github-tts-hardcases-additional-500.jsonl")]

def load_zh(path):
    rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
    return [r for r in rows if r.get('category') != 'en-core' and not any(re.match(r'^[A-Z]', x) for x in r['golden_pinyin'])]

def native_tn(texts):
    outs = subprocess.run([ZH], input=('\n'.join(texts) + '\n').encode(), capture_output=True).stdout.decode('utf-8', 'replace').split('\n')
    return outs

# cache TN once (independent of G2P lexicon)
CACHE = {}
poly_rows = [json.loads(l) for l in open(POLY, encoding='utf-8') if l.strip()]
CACHE['poly'] = (poly_rows, [r['text'] for r in poly_rows])  # pure hanzi: TN == identity
for name, path in REG:
    rows = load_zh(path)
    prepped = [frontend.frontend_prepare(r['text']) for r in rows]
    CACHE[name] = (rows, native_tn(prepped)[:len(rows)])

def score_set(rows, tnouts, toneless=False):
    ok = 0; tok_ok = 0; tok_n = 0
    for r, o in zip(rows, tnouts):
        g = pins(r['golden_pinyin']); m = pins(g2p.text_to_pinyin(o))
        if toneless:
            ok += ([strip(x) for x in m] == [strip(x) for x in g])
        else:
            ok += (m == g)
        n = max(len(m), len(g)); tok_n += n
        tok_ok += sum(1 for a, b in zip(m, g) if a == b)
    return ok, len(rows), tok_ok, tok_n

def run(label, purge=()):
    saved = {w: g2p.WP[w] for w in purge if w in g2p.WP}
    for w in purge: g2p.WP.pop(w, None)
    line = [label]
    po, pn, ptk, ptn = score_set(*CACHE['poly'])
    pt, _, _, _ = score_set(*CACHE['poly'], toneless=True)
    line.append(f"poly {po}/{pn} ({100*po/pn:.1f}%) tok {100*ptk/ptn:.2f}% noTone {100*pt/pn:.1f}%")
    for name, _ in REG:
        o, n, _, _ = score_set(*CACHE[name])
        line.append(f"{name} {o}/{n}")
    g2p.WP.update(saved)
    print("  ".join(line))

REDUNDANT = ['后重','并重','新乐','小乐','传中','的传','先系','在朝','行名','现银','中发','直着','着着','后调']
NONREDUN  = ['了案','却还','的历','了知']
FINAL     = REDUNDANT + ['却还','的历']  # non-真词, safe to delete

run("baseline               ")
run("purge REDUNDANT        ", REDUNDANT)
run("purge REDUNDANT+ALL_NON", REDUNDANT + NONREDUN)
run("purge FINAL (chosen)   ", FINAL)
