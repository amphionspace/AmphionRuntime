#!/usr/bin/env python3
# Prototype polyphone_phrases.txt additions and measure impact WITHOUT touching the
# real resource file (monkeypatch g2p.OVR, which the device applies via
# restoreOverridePinyin substring-search — robust to greedy mis-segmentation).
import json, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
import g2p

PIN = re.compile(r'^[a-z]+[0-6]$')
pins = lambda l: [x for x in l if PIN.match(x)]
strip = lambda s: s[:-1] if PIN.match(s) else s
HANZI = re.compile(r'[\u4e00-\u9fff]')
PATH = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/高频多音字复杂句子语料500条-逐句独立版.jsonl"

# Defensible device-wrong collocations (fasten-系, chóng-重, zhuàn-传, etc.).
# These correct genuine wrong-SYLLABLE polyphone reads (not tone convention).
FIXES = {
    # 系 = jì "fasten/tie" (device defaults to xì)
    "系牢": "ji4 lao2", "系安全带": "ji4 an1 quan2 dai4", "系围裙": "ji4 wei2 qun2",
    "系好": "ji4 hao3",
    # 重 = chóng "again/re-" broken by spurious 后重/并重
    "重播": "chong2 bo1", "重新": "chong2 xin1", "重复": "chong2 fu4",
    # 传 = zhuàn "biography" broken by spurious 在列/传中
    "列传": "lie4 zhuan4", "传记": "zhuan4 ji4", "自传": "zi4 zhuan4", "经传": "jing1 zhuan4",
    # 差 = chāi "business trip"
    "出差": "chu1 chai1",
    # 着 = zháo "anxious"
    "着急": "zhao2 ji2",
    # 调 = tiáo "mediate"
    "调解": "tiao2 jie3",
    # 薄 = báo "thin (slice)"
    "薄片": "bao2 pian4", "薄饼": "bao2 bing3",
    # 乐 = yuè "music" broken by spurious 新乐
    "乐曲": "yue4 qu3",
}

def score(overrides=None):
    saved = dict(g2p.OVR)
    if overrides:
        g2p.OVR.update(overrides)
    dev_ok = tone_ok = 0
    ws = 0  # wrong-syllable tokens
    for r in [json.loads(l) for l in open(PATH, encoding='utf-8') if l.strip()]:
        g = pins(r['golden_pinyin'])
        m = pins(g2p.text_to_pinyin(r['text']))
        dev_ok += (m == g)
        if len(m) == len(g):
            tone_ok += ([strip(x) for x in m] == [strip(x) for x in g])
            ws += sum(1 for a, b in zip(m, g) if strip(a) != strip(b))
    g2p.OVR.clear(); g2p.OVR.update(saved)
    return dev_ok, tone_ok, ws

b_dev, b_tone, b_ws = score()
a_dev, a_tone, a_ws = score(FIXES)
print(f"BASELINE : device={b_dev}/500 ({100*b_dev/500:.1f}%)  tone-insensitive={b_tone}/500 ({100*b_tone/500:.1f}%)  wrong-syllable-tokens={b_ws}")
print(f"WITH FIX : device={a_dev}/500 ({100*a_dev/500:.1f}%)  tone-insensitive={a_tone}/500 ({100*a_tone/500:.1f}%)  wrong-syllable-tokens={a_ws}")
print(f"DELTA    : device +{a_dev-b_dev}  tone-insensitive +{a_tone-b_tone}  wrong-syllable -{b_ws-a_ws}")
