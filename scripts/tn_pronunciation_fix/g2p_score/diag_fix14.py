#!/usr/bin/env python3
import json, re, os, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import g2p
PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
PATH = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"
rows = [json.loads(l) for l in open(PATH, encoding='utf-8') if l.strip()]

def seg(text):
    parts=[];i=0
    while i<len(text):
        st=g2p.surname_title(text,i)
        if st: parts.append(text[i:i+st[0]]);i+=st[0];continue
        w=g2p.longest_word(text,i);parts.append(w);i+=len(w)
    return parts
def segrun(text):
    return [ '/'.join(seg(m.group(0))) for m in re.finditer(r'[\u4e00-\u9fff]+',text) ]

print("=== 残留 的/了 劫持诊断 ===")
for rid in ['polyphone-independent-11-11','polyphone-independent-18-05','polyphone-independent-12-09','polyphone-independent-21-14']:
    r=next(x for x in rows if x['id']==rid)
    print(f"\n{rid}: {r['text']}")
    print("  seg:", segrun(r['text']))

print("\n=== 全集所有含'一行'的句子 (看后接字, 判断 hang2/xing2) ===")
for r in rows:
    for mo in re.finditer('一行(.?)', r['text']):
        # find golden reading of 行 at that position
        idx=len([c for c in r['text'][:mo.start()+1] if '\u4e00'<=c<='\u9fff'])  # index of 行
        g=pins(r['golden_pinyin'])
        gh=g[idx] if idx<len(g) else '?'
        print(f"  一行[{mo.group(1)}] 行golden={gh:6} | {r['text']}")

print("\n=== 全集所有含'得'的句子里, 得的 golden 读音分布 ===")
cnt=collections.Counter()
for r in rows:
    hanzi=[c for c in r['text'] if '\u4e00'<=c<='\u9fff']
    g=pins(r['golden_pinyin'])
    if len(hanzi)!=len(g): continue
    for k,c in enumerate(hanzi):
        if c=='得':
            ctx=''.join(hanzi[max(0,k-1):k+2])
            cnt[(ctx,g[k])]+=1
for (ctx,gg),n in sorted(cnt.items()):
    print(f"  {ctx:6} 得={gg:6} x{n}")
