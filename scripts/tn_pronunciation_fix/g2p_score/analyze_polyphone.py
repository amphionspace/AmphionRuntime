#!/usr/bin/env python3
# Separate genuine G2P/segmentation polyphone errors from tone-sandhi convention
# noise on the pure-hanzi polyphone set.
import json, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
import g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
HANZI = re.compile(r'[\u4e00-\u9fff]')

PATH = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"

def no_sandhi_pinyin(text):
    """device g2p WITHOUT any tone sandhi (citation tones) — pure lexicon lookup."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if HANZI.match(text[i]):
            j = i
            while j < n and HANZI.match(text[j]):
                j += 1
            out += g2p.hanzi_chunk_to_pinyin(text[i:j])
            i = j
        else:
            i += 1
    return out

def strip_tone(s):
    return s[:-1] if PIN.match(s) else s

rows = [json.loads(l) for l in open(PATH, encoding='utf-8') if l.strip()]

sent_sandhi = sent_nosandhi = sent_toneless = 0
genuine_err = collections.Counter()      # char: mine->gold with sandhi removed
genuine_ex = collections.defaultdict(list)
toneless_err = collections.Counter()     # wrong syllable ignoring tone entirely
toneless_ex = collections.defaultdict(list)

for r in rows:
    g = pins(r['golden_pinyin'])
    m_sandhi = pins(g2p.text_to_pinyin(r['text']))
    m_plain = pins(no_sandhi_pinyin(r['text']))
    sent_sandhi += (m_sandhi == g)
    sent_nosandhi += (m_plain == g)
    sent_toneless += ([strip_tone(x) for x in m_plain] == [strip_tone(x) for x in g])
    hanzi = [c for c in r['text'] if '\u4e00' <= c <= '\u9fff']
    if len(hanzi) == len(g) == len(m_plain):
        for ch, gp, mp in zip(hanzi, g, m_plain):
            if gp != mp:
                genuine_err[(ch, mp, gp)] += 1
                if len(genuine_ex[(ch, mp, gp)]) < 3:
                    genuine_ex[(ch, mp, gp)].append(r['text'])
            if strip_tone(gp) != strip_tone(mp):
                toneless_err[(ch, strip_tone(mp), strip_tone(gp))] += 1
                if len(toneless_ex[(ch, strip_tone(mp), strip_tone(gp))]) < 3:
                    toneless_ex[(ch, strip_tone(mp), strip_tone(gp))].append(r['text'])

N = len(rows)
print(f"sentence PASS (device w/ sandhi)   : {sent_sandhi}/{N} = {100*sent_sandhi/N:.1f}%")
print(f"sentence PASS (citation, no sandhi): {sent_nosandhi}/{N} = {100*sent_nosandhi/N:.1f}%")
print(f"sentence PASS (tone-insensitive)   : {sent_toneless}/{N} = {100*sent_toneless/N:.1f}%")

print(f"\n=== GENUINE errors (no-sandhi vs golden), by char: mine->gold : count ===")
print(f"total genuine wrong tokens: {sum(genuine_err.values())}")
for (ch, mp, gp), n in genuine_err.most_common(60):
    print(f"  {ch}: {mp} -> {gp}  x{n}   e.g. {genuine_ex[(ch,mp,gp)][0]}")

print(f"\n=== WRONG-SYLLABLE errors (ignoring tone) — real polyphone bugs ===")
print(f"total tone-insensitive wrong tokens: {sum(toneless_err.values())}")
for (ch, mp, gp), n in toneless_err.most_common(60):
    print(f"  {ch}: {mp} -> {gp}  x{n}   e.g. {toneless_ex[(ch,mp,gp)][0]}")
