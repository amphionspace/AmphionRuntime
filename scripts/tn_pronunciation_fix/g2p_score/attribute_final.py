#!/usr/bin/env python3
# Precisely attribute WHY sentences fail on polyphone-500 (current landed state):
# split failures into "tone-only" (would pass if tone ignored) vs "wrong-syllable"
# (真读错), and break tone-only failures down by cause (三声变调 / 一不变调 / 轻声 / 其它).
import json, re, os, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
PATH = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"

rows = [json.loads(l) for l in open(PATH, encoding='utf-8') if l.strip()]

n_pass = n_toneonly = n_wrongsyl = 0
cause = collections.Counter()  # per tone-diff token cause, within tone-only fails
for r in rows:
    g = pins(r['golden_pinyin'])
    m = pins(g2p.text_to_pinyin(r['text']))
    hanzi = [c for c in r['text'] if '\u4e00' <= c <= '\u9fff']
    if m == g:
        n_pass += 1; continue
    if len(m) != len(g):
        n_wrongsyl += 1; continue
    toneless = [strip(x) for x in m] == [strip(x) for x in g]
    if not toneless:
        n_wrongsyl += 1; continue
    n_toneonly += 1
    # classify each tone-diff token
    for k in range(len(g)):
        if m[k] == g[k]:
            continue
        ch = hanzi[k] if k < len(hanzi) else '?'
        mm, gg = m[k], g[k]
        if ch == '一':
            cause['一 变调 (yi1->yi2/yi4)'] += 1
        elif ch == '不':
            cause['不 变调 (bu4->bu2)'] += 1
        elif mm.endswith('2') and gg.endswith('3'):
            cause['三声变调 (X3->X2)'] += 1
        elif mm.endswith('5') or gg.endswith('5'):
            cause['轻声约定 (轻声<->本调)'] += 1
        else:
            cause['其它声调差异'] += 1

N = len(rows)
print(f"总句数 {N}")
print(f"  完全通过            : {n_pass}  ({100*n_pass/N:.1f}%)")
print(f"  失败-仅声调/变调    : {n_toneonly}  ({100*n_toneonly/N:.1f}%)  <- 忽略声调就能过")
print(f"  失败-真读错音节     : {n_wrongsyl}  ({100*n_wrongsyl/N:.1f}%)  <- 声母/韵母选错")
print(f"\n失败句共 {N-n_pass} 句, 其中 {n_toneonly} 句({100*n_toneonly/(N-n_pass):.0f}%)纯声调, {n_wrongsyl} 句({100*n_wrongsyl/(N-n_pass):.0f}%)真读错")
print(f"\n=== '仅声调'失败里, 错误 token 的成因分布 ===")
tot = sum(cause.values())
for k, v in cause.most_common():
    print(f"  {k:26} {v:4}  ({100*v/tot:.0f}%)")
