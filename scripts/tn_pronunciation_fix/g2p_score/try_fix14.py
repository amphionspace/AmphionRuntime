#!/usr/bin/env python3
# Verify the 14-sentence fix (on top of current landed Tier-1/Tier-2) is net-positive
# and zero-regression: add 4 phrase overrides + delete 4 hijacker lexicon entries.
import json, re, os, sys, subprocess
sys.path.insert(0, os.path.dirname(__file__))
import frontend, g2p
PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
ZH = os.environ.get("ZH_TTS")
B = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/"
POLY = B + "高频多音字复杂句子语料500条-逐句独立版.jsonl"
REG = [("round15", B+"pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl"),
       ("hard500", B+"github-tts-hardcases-500.jsonl"),
       ("addl500", B+"github-tts-hardcases-additional-500.jsonl")]
def load_zh(path):
    rr=[json.loads(l) for l in open(path,encoding='utf-8') if l.strip()]
    return [r for r in rr if r.get('category')!='en-core' and not any(re.match(r'^[A-Z]',x) for x in r['golden_pinyin'])]
def native(texts):
    return subprocess.run([ZH],input=('\n'.join(texts)+'\n').encode(),capture_output=True).stdout.decode('utf-8','replace').split('\n')
CACHE={}
pr=[json.loads(l) for l in open(POLY,encoding='utf-8') if l.strip()]
CACHE['poly']=(pr,[r['text'] for r in pr])
for name,path in REG:
    rows=load_zh(path); CACHE[name]=(rows,native([frontend.frontend_prepare(r['text']) for r in rows])[:len(rows)])
def sset(rows,outs,toneless=False):
    ok=tok=n=0
    for r,o in zip(rows,outs):
        g=pins(r['golden_pinyin']); m=pins(g2p.text_to_pinyin(o))
        ok += ([strip(x) for x in m]==[strip(x) for x in g]) if toneless else (m==g)
        n+=max(len(m),len(g)); tok+=sum(1 for a,b in zip(m,g) if a==b)
    return ok,len(rows),tok,n
ADD_OVR={"得注意":"dei3 zhu4 yi4","得赶快":"dei3 gan3 kuai4","一行文字":"yi1 hang2 wen2 zi4","一行业务":"yi1 hang2 ye4 wu4"}
DEL_WP=["面的","的证","了案","了知"]
def run(label,ovr=None,delwp=()):
    so=dict(g2p.OVR); sw={w:g2p.WP[w] for w in delwp if w in g2p.WP}
    if ovr: g2p.OVR.update(ovr)
    for w in delwp: g2p.WP.pop(w,None)
    po,pn,ptk,ptn=sset(*CACHE['poly']); pt,_,_,_=sset(*CACHE['poly'],toneless=True)
    line=[label,f"poly {po}/{pn} ({100*po/pn:.1f}%) tok {100*ptk/ptn:.2f}% noTone {100*pt/pn:.1f}%"]
    for name,_ in REG:
        o,n,_,_=sset(*CACHE[name]); line.append(f"{name} {o}/{n}")
    g2p.OVR.clear(); g2p.OVR.update(so); g2p.WP.update(sw)
    print("  ".join(line))
run("baseline (T1+T2)   ")
run("+14fix (chosen)    ",ADD_OVR,DEL_WP)
