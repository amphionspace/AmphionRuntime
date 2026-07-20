#!/usr/bin/env python3
"""Export A-class (suspected golden annotation errors) from the 750 polyphone set."""
import json, re, importlib, collections, pickle, g2p
importlib.reload(g2p)
PIN = re.compile(r'^[a-z]+[0-6]$'); pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
S = '/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字逐句独立语料750条.jsonl'
rows = {}
for l in open(S, encoding='utf-8'):
    if l.strip():
        r = json.loads(l); rows[r['id']] = r
A = pickle.load(open('/tmp/cls750.pkl', 'rb'))['A']
reason = {
 '地': '结构助词/状语“地”应读轻声 de5，golden 标注为实词 di4',
 '长': '时长/长度义应读 cháng，golden 标注为 zhǎng（生长/首长义）',
 '藏': '专名 西藏/藏文/藏族/藏毯 应读 Zàng，golden 标注为 cáng（收藏义）',
 '还': '归还/偿还/还款义应读 huán，golden 标注为 hái（副词义）',
 '乐': '乐曲/音乐义应读 yuè，golden 标注为 lè（欢乐义）',
 '调': '调节/调整/调高义应读 tiáo，golden 标注为 diào',
 '重': '重整/重新（再次义）应读 chóng、重视/重点（程度义）应读 zhòng，golden 标反',
 '弹': '弹奏义应读 tán，golden 标注为 dàn（子弹义）',
 '解': '理解义应读 jiě，golden 标注为 xiè（姓氏/解送义）',
 '差': '钦差/官差应读 chāi、差异应读 chā，golden 标反',
 '朝': '朝向/朝南义应读 cháo，golden 标注为 zhāo（早晨义）',
 '行': '银行/跨行/首行/下一行/行号（行当/行列义）应读 háng，golden 标注为 xíng',
 '得': '得到/得奖（获得义）应读 dé，golden 标注为 děi（必须义）',
}
by = collections.defaultdict(list)
for i, t, disp in A:
    r = rows[i]; g = pins(r['golden_pinyin']); m = pins(g2p.text_to_pinyin(t))
    hz = [c for c in t if '\u4e00' <= c <= '\u9fff']
    errs = [(k, hz[k], strip(m[k]), strip(g[k])) for k in range(len(g)) if strip(m[k]) != strip(g[k])]
    by[errs[0][1]].append((i, t, errs))
order = ['地', '长', '行', '藏', '还', '乐', '调', '重', '弹', '解', '差', '朝', '得']
o = []
o.append('# 多音字语料 750 条 — golden 标注疑误清单（A 类）')
o.append('')
o.append('> 说明：以下 %d 句中，端侧 G2P（前端分词 + 多音字词典）在上下文中输出的读音是正确的，而语料 `golden_pinyin` 标注疑似有误。' % len(A))
o.append('> 仅列“忽略声调仍不一致”（即声母/韵母选择不同）的真读错，不含变调/轻声约定差异。建议 golden 作者复核。')
o.append('')
o.append('| 字 | 疑误 token 数 | 规律 |')
o.append('|---|---|---|')
for c in order:
    if by[c]:
        tok = sum(1 for e in by[c] for k, ch, a, b in e[2] if ch == c)
        o.append('| %s | %d | %s |' % (c, tok, reason.get(c, '')))
o.append('')
for c in order:
    if not by[c]:
        continue
    o.append('## %s（%s）' % (c, reason.get(c, '')))
    o.append('')
    for i, t, errs in by[c]:
        estr = '；'.join('第%d个“%s” 设备=%s / golden=%s' % (k + 1, ch, a, b) for k, ch, a, b in errs if ch == c)
        o.append('- `%s` %s' % (i, t))
        o.append('  - %s' % estr)
    o.append('')
open('/Users/amphion/Desktop/work/reference/AmphionRuntime/scripts/tn_pronunciation_fix/GOLDEN_ISSUES_polyphone750.md', 'w', encoding='utf-8').write('\n'.join(o))
print('written', len(A), 'sentences;', {c: len(by[c]) for c in order if by[c]})
