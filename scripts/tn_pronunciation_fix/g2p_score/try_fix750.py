#!/usr/bin/env python3
# Verify the 750-set fix across ALL sets. Zero-regression = g2p output byte-identical
# on regression-set inputs before vs after (isolates the change from the TN layer).
import json, re, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import g2p
PIN = re.compile(r'^[a-z]+[0-6]$'); pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
B = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/"
POLY = {"poly500": B+"高频多音字复杂句子语料500条-逐句独立版.jsonl",
        "poly750": B+"高频多音字逐句独立语料750条.jsonl"}
REG = {"round15": B+"pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl",
       "hard500": B+"github-tts-hardcases-500.jsonl",
       "addl500": B+"github-tts-hardcases-additional-500.jsonl"}
def rows(p): return [json.loads(l) for l in open(p,encoding='utf-8') if l.strip()]
POLYR={k:rows(v) for k,v in POLY.items()}
REGR={k:rows(v) for k,v in REG.items()}
def polyscore(rs):
    ok=t=n=0
    for r in rs:
        g=pins(r['golden_pinyin']); m=pins(g2p.text_to_pinyin(r['text']))
        ok+= m==g; t+= [strip(x) for x in m]==[strip(x) for x in g]; n+=1
    return ok,t,n
def g2p_snapshot(rs): return [g2p.text_to_pinyin(r['text']) for r in rs]
ADD_OVR={"行长":"hang2 zhang3","班长":"ban1 zhang3","董事长":"dong3 shi4 zhang3","园长":"yuan2 zhang3",
 "家长":"jia1 zhang3","长高":"zhang3 gao1","长大":"zhang3 da4","长出":"zhang3 chu1",
 "收藏":"shou1 cang2","隐藏":"yin3 cang2","角色":"jue2 se4","主角":"zhu3 jue2","配角":"pei4 jue2",
 "着凉":"zhao2 liang2","钦差":"qin1 chai1","官差":"guan1 chai1","差遣":"chai1 qian3",
 "重整":"chong2 zheng3","重读":"chong2 du2",
 "行号":"hang2 hao4","逐行":"zhu2 hang2","首行":"shou3 hang2","下一行":"xia4 yi4 hang2",
 "得重新":"dei3 chong2 xin1","得继续":"dei3 ji4 xu4","得立即":"dei3 li4 ji2","得抓紧":"dei3 zhua1 jin3","得赶":"dei3 gan3"}
DEL_WP=["还主","还返","还意","了不"]
base_reg={k:g2p_snapshot(v) for k,v in REGR.items()}
base_poly={k:polyscore(v) for k,v in POLYR.items()}
# apply
g2p.OVR.update(ADD_OVR)
for w in DEL_WP: g2p.WP.pop(w,None)
fix_reg={k:g2p_snapshot(v) for k,v in REGR.items()}
fix_poly={k:polyscore(v) for k,v in POLYR.items()}
print("=== polyphone sets (sentence / toneless / n) ===")
for k in POLY:
    bo,bt,n=base_poly[k]; fo,ft,_=fix_poly[k]
    print(f"  {k}: {bo}/{n}({100*bo/n:.1f}%) -> {fo}/{n}({100*fo/n:.1f}%)  |  toneless {100*bt/n:.1f}% -> {100*ft/n:.1f}%")
print("=== regression sets: sentences whose g2p output CHANGED ===")
for k in REG:
    ch=[(REGR[k][i]['text'],base_reg[k][i],fix_reg[k][i]) for i in range(len(REGR[k])) if base_reg[k][i]!=fix_reg[k][i]]
    print(f"  {k}: {len(ch)} changed / {len(REGR[k])}")
    for txt,b,f in ch[:20]:
        diff=[(b[j],f[j]) for j in range(min(len(b),len(f))) if b[j]!=f[j]]
        print(f"     {txt[:40]}  {diff}")
