#!/usr/bin/env python3
# Port of the Kotlin TN frontend pre-processing (LitsTnNormalizer.LayoutNormalizer)
# so the harness runs the FULL device TN pipeline: clean(NFKC) -> prepareInputForTn
# -> (native zh_tts rules_v2). Ported faithfully from LitsTnNormalizer.kt +
# FrontendRuleSet.kt. Zh path.
import re, json, unicodedata, os

D="/Users/amphion/Desktop/work/reference/AmphionRuntime/tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0"
CH={'0':'零','1':'一','2':'二','3':'三','4':'四','5':'五','6':'六','7':'七','8':'八','9':'九'}
TECH_SYM=set('./\\_@:?=&#%+-')

def digitSeqToHanzi(t): return ''.join(CH.get(c,c) for c in t)
def intToHanzi(t):
    try: v=int(t)
    except: return digitSeqToHanzi(t)
    if v==0: return '零'
    if v<10: return CH[str(v)]
    if v<20:
        o=v%10; return '十'+('' if o==0 else CH[str(o)])
    if v<100:
        te=v//10; o=v%10; return CH[str(te)]+'十'+('' if o==0 else CH[str(o)])
    h=v//100; r=v%100
    tail='' if r==0 else ('零'+CH[str(r)] if r<10 else intToHanzi(str(r)))
    return CH[str(h)]+'百'+tail
def numberTextToHanzi(t):
    p=t.split('.',1); integer=intToHanzi(p[0])
    if len(p)==1: return integer
    return integer+'点'+''.join(CH[c] for c in p[1])
# Big-number cardinal reading (native RBNF only spells out <=6 digits; >=7 read
# digit-by-digit). Standard 万/亿 segmentation with correct 零 handling.
_BIG=['','万','亿','万亿','亿亿']
def _fourHanzi(n):
    s=''; zero=False; started=False
    for pos in range(3,-1,-1):
        d=(n//(10**pos))%10
        if d==0:
            if started: zero=True
        else:
            if zero: s+='零'; zero=False
            s+=CH[str(d)]+['','十','百','千'][pos]; started=True
    return s
def bigCardinal(n):
    if n==0: return '零'
    segs=[]; x=n
    while x>0: segs.append(x%10000); x//=10000
    if len(segs)>len(_BIG): return None
    res=''
    for i in range(len(segs)-1,-1,-1):
        seg=segs[i]
        if seg==0: continue
        if res and seg<1000: res+='零'
        res+=_fourHanzi(seg)+_BIG[i]
    return res
R_bigcardinal=re.compile(r'(?<![0-9A-Za-z.])(\d{7,15})(?![0-9])')  # not after '.' (decimal tail reads digit-by-digit)
def expandBigCardinal(text):
    return R_bigcardinal.sub(lambda m: bigCardinal(int(m.group(1))) or m.group(0), text)

def versionToHanzi(t): return '点'.join(digitSeqToHanzi(x) for x in t.split('.'))
def normSerial(code): return ''.join(CH.get(c,c) for c in code)

# --- FrontendRuleSet (frontend_rules.json) ---
def load_frontend_rules():
    p=os.path.join(D,'frontend_rules.json')
    if not os.path.isfile(p): return []
    out=[]
    for it in json.load(open(p,encoding='utf-8')).get('replacements',[]):
        pat=it.get('pattern',''); rep=it.get('replacement',''); st=it.get('stages',[])
        if not pat or not rep or not st: continue
        out.append((set(st), re.compile(pat, re.I), rep))
    return out
FRULES=load_frontend_rules()
def render_repl(template, groups):
    out=[]; i=0
    while i<len(template):
        c=template[i]
        if c=='$' and i+1<len(template) and template[i+1].isdigit():
            gi=int(template[i+1]); out.append(groups[gi] if gi<len(groups) else ''); i+=2
        else: out.append(c); i+=1
    return ''.join(out)
def frontend_apply(stage, text):
    for stages,rgx,rep in FRULES:
        if stage in stages:
            text=rgx.sub(lambda m: render_repl(rep,[m.group(0)]+list(m.groups())), text)
    return text

# --- regexes (from LitsTnNormalizer.kt) ---
R_hanziClock=re.compile(r'([零一二三四五六七八九十两]+)点0([1-9])分')
R_percent=re.compile(r'(\d+(?:\.\d+)?)\s?[%％]')
R_percentText=re.compile(r'(\d+(?:\.\d+)?)\s?百分号')
R_clockColon=re.compile(r'(?<!\d)(\d{1,2}):0([0-9])(?!\d)')
R_year=re.compile(r'(?<!\d)(\d{4})\s*年')
R_year2=re.compile(r'(?<!\d)(0\d)年')  # leading-zero 2-digit year digit-by-digit: 05年->零五年 (not 35年)
# leading minus before a number / percent -> 负 (not a range like 1-2, whose - follows a digit)
R_neg=re.compile(r'(?<![0-9A-Za-z一-鿿])[-−](?=\d|百分之)')
R_semver=re.compile(r'(?<![A-Za-z0-9])([vV])(\d+(?:\.\d+)+)(?![A-Za-z0-9])')
R_techToken=re.compile(r'(?<![A-Za-z0-9])([A-Za-z0-9./\\_@:?=&#%+\-]*[A-Za-z0-9])(?![A-Za-z0-9])')
R_chem=re.compile(r'\b(H|CO)(\d+)(O?)\b')
R_room=re.compile(r'((?:房间|房号)(?:是|为)?\s*)(\d{3,4})(?!\d)')
R_stock=re.compile(r'(股票\s*)(\d{6})(?!\d)')
R_plate=re.compile(r'((?:车牌号?|号牌)\s*[一-鿿]?\s*[A-Za-z])(\d{3,6})(?!\d)')
R_idtail=re.compile(r'((?:身份证尾号|尾号)\s*)(\d+)([A-Za-z])(?![A-Za-z0-9])')
R_pathslash=re.compile(r'(/)(\d+)(?=/)')
R_kmh=re.compile(r'(\d+)\s*km/h', re.I)
R_coord=re.compile(r'(?<![A-Za-z])([NE])\s*(\d+(?:\.\d+)?)', re.I)
R_vin=re.compile(r'((?:车架号\s*)?(?:VIN\s+))([A-HJ-NPR-Z0-9]{8,17})(?![A-Za-z0-9])', re.I)
R_product=re.compile(r'(?<![A-Za-z0-9])(vocos|Office)(\d+)(k?)(?![A-Za-z0-9])', re.I)
R_serial=re.compile(r'((?:设备)?(?:序列号|编号)|S/N|SN)(\s*)([A-Z0-9]*[A-Z][A-Z0-9]*\d[A-Z0-9]*)')

# Dates with -, /, . separators. Run BEFORE the fraction/range/decimal/path rules
# (which otherwise read 2008/08 as 八分之二千零八, 2008-08 as 二千零八至八, etc.).
# Segments must be a 4-digit year or exactly 2 digits; month 1-12, day 1-31 gate out
# scores/fractions/decimals/IPs (1/2, 中国1-2, 13.5, 127.0.0.1 all have a 1-digit seg).
R_dateYMD=re.compile(r'(?<![0-9A-Za-z])(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?![0-9])')
R_dateMDY=re.compile(r'(?<![0-9A-Za-z])(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?![0-9])')
# two-segment YM/MY: month must be zero-padded 2 digits (golden always is), so
# a decimal like 5.5555 (1-digit + 4-digit) is NOT mistaken for MM.YYYY.
R_dateYM =re.compile(r'(?<![0-9A-Za-z])(\d{4})[-/.](0[1-9]|1[0-2])(?![0-9])')
R_dateMY =re.compile(r'(?<![0-9A-Za-z])(0[1-9]|1[0-2])[-/.](\d{4})(?![0-9])')
R_dateMD =re.compile(r'(?<![0-9A-Za-z])(\d{2})[-/.](\d{2})(?![0-9])')
R_time=re.compile(r'(?<!\d)(\d{1,2}):([0-5]\d)(?::([0-5]\d))?(?!\d)')  # HH:MM[:SS] -> H点M分[S秒]
def expandTime(text):
    def rep(m):
        h,mm,ss=m.group(1),m.group(2),m.group(3)
        s=intToHanzi(h)+'点'+intToHanzi(str(int(mm)))+'分'
        if ss is not None: s+=intToHanzi(str(int(ss)))+'秒'
        return s
    return R_time.sub(rep,text)
def _vMonth(mo): return 1<=int(mo)<=12
def _vDay(d):    return 1<=int(d)<=31
def _ym(y,mo):   return digitSeqToHanzi(y)+'年'+intToHanzi(str(int(mo)))+'月'
def expandDates(text):
    def ymd(m):
        y,mo,d=m.groups()
        return _ym(y,mo)+intToHanzi(str(int(d)))+'日' if _vMonth(mo) and _vDay(d) else m.group(0)
    text=R_dateYMD.sub(ymd, text)
    def mdy(m):
        mo,d,y=m.groups()
        return _ym(y,mo)+intToHanzi(str(int(d)))+'日' if _vMonth(mo) and _vDay(d) else m.group(0)
    text=R_dateMDY.sub(mdy, text)
    text=R_dateYM.sub(lambda m:_ym(m.group(1),m.group(2)) if _vMonth(m.group(2)) else m.group(0), text)
    text=R_dateMY.sub(lambda m:_ym(m.group(2),m.group(1)) if _vMonth(m.group(1)) else m.group(0), text)
    def md(m):
        mo,d=m.groups()
        return intToHanzi(str(int(mo)))+'月'+intToHanzi(str(int(d)))+'日' if _vMonth(mo) and _vDay(d) else m.group(0)
    text=R_dateMD.sub(md, text)
    return text

# Superscript area/volume units (m²/km²/m³...). NFKC folds ²->2 and ³->3, destroying
# the exponent, so expand BEFORE clean(): <num><unit><²|³> -> <num>(平方|立方)<unit_zh>.
UNIT_ZH={'km':'千米','cm':'厘米','mm':'毫米','dm':'分米','m':'米'}
R_supUnit=re.compile(r'(\d+(?:\.\d+)?)\s*(km|cm|mm|dm|m)([²³])')
def expandSuperscriptUnits(text):
    def rep(m):
        exp='平方' if m.group(3)=='²' else '立方'
        return numberTextToHanzi(m.group(1))+exp+UNIT_ZH[m.group(2).lower()]
    return R_supUnit.sub(rep, text)

def isAsciiLetter(c): return 'a'<=c<='z' or 'A'<=c<='Z'

def normalizeTechnicalAsciiToken(token):
    out=[]; i=0
    while i<len(token):
        c=token[i]
        if c.isdigit():
            s=i
            while i<len(token) and token[i].isdigit(): i+=1
            out.append(digitSeqToHanzi(token[s:i]))
            if i<len(token) and (token[i] in TECH_SYM or isAsciiLetter(token[i])): out.append(',')
            continue
        elif isAsciiLetter(c):
            s=i
            while i<len(token) and isAsciiLetter(token[i]): i+=1
            w=token[s:i]; out.append('LITS' if w.lower()=='lits' else w); continue
        elif c=='@': out.append(' at ')
        elif c=='_': out.append(' UNDERSCORE ')
        elif c=='+': out.append('加')
        elif c=='-': out.append('杠')
        elif c=='.': out.append('点')
        elif c==':': out.append('冒号')
        elif c in '/\\': out.append('斜杠')
        elif c=='?': out.append('问号')
        elif c=='=': out.append('等于')
        elif c=='&': out.append('和')
        else: out.append(c)
        i+=1
    return re.sub(r'\s+',' ',''.join(out))

def protectTechnicalAscii(text):
    text=R_chem.sub(lambda m: m.group(1)+digitSeqToHanzi(m.group(2))+m.group(3), text)
    def tok(m):
        t=m.group(1)
        if not any(isAsciiLetter(c) for c in t) or not any(c in TECH_SYM for c in t): return t
        return normalizeTechnicalAsciiToken(t)
    return R_techToken.sub(tok, text)

def protectSemanticNumeric(text):
    text=R_percent.sub(lambda m:'百分之'+numberTextToHanzi(m.group(1)), text)
    text=R_percentText.sub(lambda m:'百分之'+numberTextToHanzi(m.group(1)), text)
    def coord(m):
        pre={'N':'北纬','E':'东经'}.get(m.group(1).upper(), m.group(1))
        return pre+numberTextToHanzi(m.group(2))
    text=R_coord.sub(coord, text)
    text=R_semver.sub(lambda m:m.group(1)+versionToHanzi(m.group(2)), text)
    text=R_stock.sub(lambda m:m.group(1)+digitSeqToHanzi(m.group(2)), text)
    text=R_room.sub(lambda m:m.group(1)+digitSeqToHanzi(m.group(2)), text)
    text=R_plate.sub(lambda m:m.group(1)+digitSeqToHanzi(m.group(2))+',', text)
    text=R_idtail.sub(lambda m:m.group(1)+digitSeqToHanzi(m.group(2))+m.group(3)+',', text)
    text=R_pathslash.sub(lambda m:m.group(1)+digitSeqToHanzi(m.group(2))+',', text)
    text=R_kmh.sub(lambda m:numberTextToHanzi(m.group(1))+'千米每小时', text)
    text=R_clockColon.sub(lambda m:numberTextToHanzi(m.group(1))+'点零'+CH[m.group(2)], text)
    text=R_year.sub(lambda m:digitSeqToHanzi(m.group(1))+'年', text)
    text=R_year2.sub(lambda m:digitSeqToHanzi(m.group(1))+'年', text)
    text=R_neg.sub('负', text)
    return text

def prepare_input(text):
    text=expandTime(text)
    text=expandDates(text)
    text=R_hanziClock.sub(lambda m:m.group(1)+'点零'+CH[m.group(2)]+'分', text)
    text=frontend_apply('pre_tn', text)
    text=protectSemanticNumeric(text)
    text=expandBigCardinal(text)   # >=7-digit isolated numbers -> cardinal (after ID/phone rules)
    text=protectTechnicalAscii(text)
    text=R_vin.sub(lambda m:m.group(1)+normSerial(m.group(2)), text)
    text=R_product.sub(lambda m:m.group(1)+normSerial(m.group(2))+m.group(3), text)
    text=R_serial.sub(lambda m:m.group(1)+m.group(2)+normSerial(m.group(3)), text)
    return text

def clean(text):
    t=unicodedata.normalize('NFKC', text)
    t=re.sub(r'[\x00-\x1f\x7f-\x9f]','',t)
    t=re.sub(r'\s+',' ',t).strip()
    return t

def frontend_prepare(text, english=False):
    return prepare_input(clean(expandSuperscriptUnits(text)))

if __name__=='__main__':
    import sys
    for line in sys.stdin:
        print(frontend_prepare(line.rstrip('\n')))
