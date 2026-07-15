#!/usr/bin/env python3
# Faithful Python port of the device G2P (hanzi -> pinyin), reusing the same
# lexicon/override/polychar files and porting LitsTtsFrontend.hanziChunkToPinyin
# + tone sandhi. Used to score TN fixes end-to-end without a device.
import re, os, sys

D = "/Users/amphion/Desktop/work/reference/AmphionRuntime/tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0"
PINYIN = re.compile(r'^[a-z]+[0-6]$')
CHINESE_DIGIT_SEQUENCE = set("零〇一二三四五六七八九两幺")
CHINESE_NUMBER_CONTEXT = set("零〇一二三四五六七八九十百千万亿两点分")  # approx for 一-sandhi
POLY_SURNAME = {'区':'ou1','曾':'zeng1','解':'xie4','任':'ren2','朴':'piao2','薄':'bo2','单':'shan4','仇':'qiu2','盖':'ge3','查':'zha1','乐':'yue4','覃':'qin2','尉':'yu4','卜':'bu3','车':'ju1','石':'dan4','华':'hua4','燕':'yan1','殷':'yin1','柏':'bo2','秘':'bi4','翟':'zhai2','长':'zhang3','纪':'ji3'}
SURNAME_TITLES = ["老师","先生","女士","经理","主任","书记","医生","同学","教授","师傅","老板"]
SURNAME_TITLE_OVERRIDE = {"先生":["xian1","sheng1"]}

def _read_tsv(path, into):
    if not os.path.isfile(path): return
    for line in open(path, encoding="utf-8"):
        t=line.rstrip("\n")
        ts=t.strip()
        if not ts or ts.startswith("#"): continue
        p=t.split("\t",1) if False else ts.split("\t",1)
        if len(p)==2: into[p[0]]=p[1]

def load():
    wp={}
    for line in open(D+"/chinese_lexicon.txt",encoding="utf-8"):
        p=line.rstrip("\n").split("\t")
        if len(p)==2: wp[p[0]]=p[1]
    override={}
    _read_tsv(D+"/polyphone_phrases.txt",override)
    _read_tsv(D+"/chinese_surname_lexicon.txt",override)
    wp.update(override)
    poly=set()
    for line in open(D+"/polychar.txt",encoding="utf-8"):
        s=line.strip()
        if s: poly.add(s)
    maxlen=max((len(k) for k in wp),default=1)
    return wp,override,poly,maxlen

WP,OVR,POLY,MAXLEN = load()

def norm_pinyin(text):
    out=[]
    for s in text.strip().split():
        s=s.replace('眉','v').replace('脺','v')
        if PINYIN.match(s): out.append(s)
    return out

def lexicon_pinyin_for_word(word):
    if word in OVR:
        s=norm_pinyin(OVR[word])
        if s: return s
    direct=WP.get(word)
    if direct is not None and word not in POLY:
        s=norm_pinyin(direct)
        if s: return s
    out=[]
    for ch in word:
        py=WP.get(ch)
        if py is None: out.append(","); continue
        s=norm_pinyin(py)
        out += s if s else [","]
    return out

def longest_word(text,start):
    # multi-char overrides first
    best=None
    for k in OVR:
        if len(k)>1 and text.startswith(k,start):
            if best is None or len(k)>len(best): best=k
    if best: return best
    maxl=min(MAXLEN, len(text)-start)
    for length in range(maxl,1,-1):
        cand=text[start:start+length]
        if cand in OVR or cand in WP: return cand
    return text[start]

def surname_title(text,start):
    sp=POLY_SURNAME.get(text[start] if start<len(text) else None)
    if sp is None: return None
    title=next((t for t in SURNAME_TITLES if text.startswith(t,start+1)),None)
    if title is None: return None
    tp=SURNAME_TITLE_OVERRIDE.get(title) or lexicon_pinyin_for_word(title)
    if len(tp)!=len(title) or any(not PINYIN.match(x) for x in tp): return None
    return (1+len(title), [sp]+tp)

def hanzi_chunk_to_pinyin(text):
    out=[]; i=0
    while i<len(text):
        st=surname_title(text,i)
        if st: out+=st[1]; i+=st[0]; continue
        w=longest_word(text,i)
        out+=lexicon_pinyin_for_word(w); i+=len(w)
    return out

def change_tone(syl,tone):
    return syl[:-1]+tone if PINYIN.match(syl) else syl

def third_tone_sandhi(tokens):
    o=list(tokens); idx=[i for i,t in enumerate(o) if PINYIN.match(t)]
    for p in range(len(idx)-1):
        c,n=idx[p],idx[p+1]
        if o[c].endswith('3') and o[n].endswith('3'): o[c]=o[c][:-1]+'2'
    return o

def bu_sandhi(text,t):
    if all(c=='不' for c in text): return
    if text=="不字": return
    if len(text)==3 and text[1]=='不' and len(t)>1 and t[1].startswith("bu"): t[1]=change_tone(t[1],'5'); return
    for i,c in enumerate(text):
        if c=='不' and i+1<len(t) and t[i+1].endswith('4'): t[i]=change_tone(t[i],'2')

def yi_sandhi(text,t):
    if len(text)==3 and text[1]=='一' and text[0]==text[2]:
        if len(t)>1: t[1]=change_tone(t[1],'5')
        return
    if text.startswith("第一") and len(t)>1: t[1]=change_tone(t[1],'1')
    if text.startswith("一月") or text.startswith("一日") or text.startswith("一号"): t[0]=change_tone(t[0],'1')
    for i,c in enumerate(text):
        if c!='一' or i+1>=len(text) or (i-1>=0 and text[i-1]=='第'): continue
        cur=t[i] if i<len(t) else None; nxt=t[i+1] if i+1<len(t) else None
        if cur is None or nxt is None or not PINYIN.match(cur) or not PINYIN.match(nxt): continue
        nx=text[i+1] if i+1<len(text) else None
        if nx in CHINESE_NUMBER_CONTEXT: t[i]=change_tone(cur,'1'); continue
        t[i]=change_tone(cur, '2' if nxt.endswith('4') else '4')

def er_sandhi(text,t):
    if len(text)>1 and text[-1]=='儿' and t and t[-1].startswith("er"): t[-1]=change_tone(t[-1],'5')

def mandarin_sandhi(text,tokens):
    o=third_tone_sandhi(tokens)
    if len(text)!=len(o): return o
    if len(text)>1 and all(c in CHINESE_DIGIT_SEQUENCE for c in text): return o
    bu_sandhi(text,o); yi_sandhi(text,o); er_sandhi(text,o)
    return o

HANZI=re.compile(r'[㐀-鿿]')
def text_to_pinyin(text):
    # split into hanzi runs; hanzi -> g2p+sandhi; keep ,/. tokens; skip others
    out=[]; i=0; n=len(text)
    while i<n:
        if HANZI.match(text[i]):
            j=i
            while j<n and HANZI.match(text[j]): j+=1
            chunk=text[i:j]
            py=hanzi_chunk_to_pinyin(chunk)
            py=mandarin_sandhi(chunk,py)
            out+=py; i=j
        else:
            c=text[i]
            if c in ',.!?;:': out.append(',' if c==',' else '.')
            i+=1
    return out

if __name__=="__main__":
    for line in sys.stdin:
        print(' '.join(text_to_pinyin(line.rstrip('\n'))))
