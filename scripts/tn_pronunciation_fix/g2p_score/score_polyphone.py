#!/usr/bin/env python3
# Scorer for the pure-hanzi polyphone test set (高频多音字复杂句子语料500条).
# The set has NO digits/ascii/symbols, so TN (zh_tts) + frontend preprocessing are
# identity here; the device output is exactly g2p.text_to_pinyin(text). We score
# that directly (fast, no native binary needed). Optionally verify a sample against
# the full pipeline (frontend.py -> zh_tts -> g2p.py) if $ZH_TTS is available.
import json, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
import g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]

def load(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]

def score(path, show_fails=0):
    rows = load(path)
    ok = 0
    fails = []
    tok_ok = 0
    tok_total = 0
    for r in rows:
        g = pins(r['golden_pinyin'])
        m = pins(g2p.text_to_pinyin(r['text']))
        if m == g:
            ok += 1
        else:
            fails.append((r, g, m))
        # token-level (align only when same length)
        if len(m) == len(g):
            for a, b in zip(m, g):
                tok_total += 1
                tok_ok += (a == b)
        else:
            tok_total += max(len(m), len(g))
            tok_ok += sum(1 for a, b in zip(m, g) if a == b)
    print(f"{os.path.basename(path)}: sentence PASS {ok}/{len(rows)} = {100*ok/len(rows):.1f}%")
    print(f"  token-level: {tok_ok}/{tok_total} = {100*tok_ok/tok_total:.2f}%")
    return rows, fails

def per_char_errors(fails):
    # for each failing sentence, find positions where mine != gold (only same-length)
    counter = collections.Counter()
    examples = collections.defaultdict(list)
    for r, g, m in fails:
        text = r['text']
        # rebuild char->pinyin alignment: g2p emits one pinyin per hanzi for these
        hanzi = [c for c in text if '\u4e00' <= c <= '\u9fff']
        if len(hanzi) == len(g) == len(m):
            for ch, gp, mp in zip(hanzi, g, m):
                if gp != mp:
                    counter[(ch, mp, gp)] += 1
                    if len(examples[(ch, mp, gp)]) < 3:
                        examples[(ch, mp, gp)].append(text)
    return counter, examples

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"
    rows, fails = score(path)
    counter, examples = per_char_errors(fails)
    print(f"\nlength-mismatch fails: {sum(1 for r,g,m in fails if len(pins(g))!=len(pins(m)))}")
    print(f"\nTop per-char errors (char: mine -> gold : count):")
    for (ch, mp, gp), n in counter.most_common(40):
        print(f"  {ch}: {mp} -> {gp}  x{n}   e.g. {examples[(ch,mp,gp)][0]}")
