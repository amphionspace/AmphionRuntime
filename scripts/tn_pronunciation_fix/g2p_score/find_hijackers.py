#!/usr/bin/env python3
# (b) Root-cause: find lexicon 2+char entries that HIJACK greedy longest-match
# segmentation and cause wrong-syllable polyphone reads on the polyphone-500 set.
# Classify each candidate as REDUNDANT (its lexicon reading == char-by-char default
# reading -> deleting it changes NO pronunciation, only the segmentation boundary,
# so it is zero-risk) vs NON-REDUNDANT (deleting changes a reading -> needs care).
import json, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
import g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
HANZI = re.compile(r'[\u4e00-\u9fff]')
PATH = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"

def seg(text):
    parts = []; i = 0
    while i < len(text):
        st = g2p.surname_title(text, i)
        if st: parts.append(text[i:i + st[0]]); i += st[0]; continue
        w = g2p.longest_word(text, i); parts.append(w); i += len(w)
    return parts

def char_default(c):
    v = g2p.WP.get(c)
    return g2p.norm_pinyin(v) if v else None

def is_redundant(word):
    """lexicon reading of `word` == concatenation of per-char default readings?"""
    lex = g2p.norm_pinyin(g2p.WP.get(word, "")) if word in g2p.WP else None
    if not lex: return None
    chars = []
    for c in word:
        d = char_default(c)
        if not d: return False
        chars += d
    return chars == lex

rows = [json.loads(l) for l in open(PATH, encoding='utf-8') if l.strip()]
hijackers = collections.Counter()
examples = collections.defaultdict(list)

for r in rows:
    g = pins(r['golden_pinyin'])
    hanzi = [c for c in r['text'] if '\u4e00' <= c <= '\u9fff']
    if len(hanzi) != len(g): continue
    # position -> golden syllable (ignoring tone)
    gpos = {i: strip(g[i]) for i in range(len(g))}
    # walk segmentation over each hanzi run, tracking absolute char index in hanzi[]
    hi = 0
    for m in re.finditer(r'[\u4e00-\u9fff]+', r['text']):
        chunk = m.group(0)
        for w in seg(chunk):
            if len(w) >= 2:
                # does this multi-char word contain a char whose g2p read (no sandhi)
                # disagrees with golden (ignoring tone)? => it hijacked a boundary
                wp = g2p.lexicon_pinyin_for_word(w)
                if len(wp) == len(w):
                    bad = any(strip(wp[k]) != gpos.get(hi + k) for k in range(len(w)))
                    if bad:
                        hijackers[w] += 1
                        if len(examples[w]) < 2:
                            examples[w].append(r['text'])
            hi += len(w)

print(f"{'word':8} {'cnt':>3} {'redundant?':10} {'lex_reading':22} example")
for w, n in hijackers.most_common():
    red = is_redundant(w)
    lex = g2p.WP.get(w, '(not in WP / OVR-only)')
    tag = 'REDUNDANT' if red else ('NON-redun' if red is False else 'n/a')
    print(f"{w:8} {n:>3} {tag:10} {lex:22} {examples[w][0]}")
