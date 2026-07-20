#!/usr/bin/env python3
# List the sentences that STILL fail on a wrong SYLLABLE (声母/韵母选错, tone ignored)
# in the current landed state — golden vs device, with the offending chars marked.
import json, re, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
PATH = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"

rows = [json.loads(l) for l in open(PATH, encoding='utf-8') if l.strip()]
n = 0
for r in rows:
    g = pins(r['golden_pinyin'])
    m = pins(g2p.text_to_pinyin(r['text']))
    if m == g:
        continue
    if len(m) == len(g) and [strip(x) for x in m] == [strip(x) for x in g]:
        continue  # tone-only, skip
    n += 1
    hanzi = [c for c in r['text'] if '\u4e00' <= c <= '\u9fff']
    print(f"\n[{n}] {r['id']}  {r['text']}")
    if len(m) != len(g):
        print(f"    ⚠ 长度不一致 device={len(m)} golden={len(g)}")
        print(f"    device: {' '.join(m)}")
        print(f"    golden: {' '.join(g)}")
        continue
    diffs = []
    for k in range(len(g)):
        if strip(m[k]) != strip(g[k]):
            ch = hanzi[k] if k < len(hanzi) else '?'
            diffs.append(f"{ch}: 设备={m[k]}  golden={g[k]}")
    for d in diffs:
        print(f"    ✗ {d}")
print(f"\n共 {n} 句真读错音节")
