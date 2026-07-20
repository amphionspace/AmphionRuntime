#!/usr/bin/env python3
# Dump every WRONG-SYLLABLE (tone-insensitive) polyphone error with full sentence
# context + show the segmentation g2p chose, to judge device-wrong vs golden-wrong.
import json, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
import g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
HANZI = re.compile(r'[\u4e00-\u9fff]')
strip = lambda s: s[:-1] if PIN.match(s) else s
PATH = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"

def no_sandhi(text):
    out=[]; i=0; n=len(text)
    while i<n:
        if HANZI.match(text[i]):
            j=i
            while j<n and HANZI.match(text[j]): j+=1
            out+=g2p.hanzi_chunk_to_pinyin(text[i:j]); i=j
        else: i+=1
    return out

def seg(text):
    # show how longest_word segments a hanzi run
    parts=[]; i=0
    while i<len(text):
        st=g2p.surname_title(text,i)
        if st: parts.append(text[i:i+st[0]]); i+=st[0]; continue
        w=g2p.longest_word(text,i); parts.append(w); i+=len(w)
    return parts

rows=[json.loads(l) for l in open(PATH,encoding='utf-8') if l.strip()]
by_char=collections.defaultdict(list)
for r in rows:
    g=pins(r['golden_pinyin']); m=no_sandhi(r['text'])
    hanzi=[c for c in r['text'] if '\u4e00'<=c<='\u9fff']
    if not (len(hanzi)==len(g)==len(m)): continue
    for k,(ch,gp,mp) in enumerate(zip(hanzi,g,m)):
        if strip(gp)!=strip(mp):
            by_char[ch].append((r['text'],mp,gp))

for ch in sorted(by_char,key=lambda c:-len(by_char[c])):
    items=by_char[ch]
    print(f"\n### {ch}  ({len(items)} errors)")
    for text,mp,gp in items:
        hanzirun=''.join(c for c in text if '\u4e00'<=c<='\u9fff')
        print(f"  mine={mp:6} gold={gp:6} | {text}")
