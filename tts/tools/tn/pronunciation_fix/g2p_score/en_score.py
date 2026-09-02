import argparse, json, os, re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
D = os.environ.get(
    "TTS_MODEL_DIR",
    str(
        REPO_ROOT
        / "tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0"
    ),
)

# --- load lexicons (device: englishLexicon=cmudict, supplementLexicon=supplement.entries) ---
cmu={}
for line in open(D+"/cmudict.txt", encoding='utf-8', errors='replace'):
    m=re.match(r'^(\S+)\s+(.+)$', line.rstrip())
    if not m: continue
    base=re.sub(r'\(\d+\)$','',m.group(1))
    if base not in cmu: cmu[base]=m.group(2).split()
supp={k:v['phones'] for k,v in json.load(open(D+"/supplement_lexicon.json",encoding='utf-8'))['entries'].items()}

LP={'A':['EY1'],'B':['B','IY1'],'C':['S','IY1'],'D':['D','IY1'],'E':['IY1'],'F':['EH1','F'],'G':['JH','IY1'],'H':['EY1','CH'],'I':['AY1'],'J':['JH','EY1'],'K':['K','EY1'],'L':['EH1','L'],'M':['EH1','M'],'N':['EH1','N'],'O':['OW1'],'P':['P','IY1'],'Q':['K','Y','UW1'],'R':['AA1','R'],'S':['EH1','S'],'T':['T','IY1'],'U':['Y','UW1'],'V':['V','IY1'],'W':['D','AH1','B','AH0','L','Y','UW0'],'X':['EH1','K','S'],'Y':['W','AY1'],'Z':['Z','IY1']}
OVR={"AUDIO":["AO1","D","IY0","OW2"],"UNDERSCORE":["AH2","N","D","ER0","S","K","AO1","R"],"WIFI":["W","AY1","F","AY1"],"WI-FI":["W","AY1","F","AY1"],"TIMEOUT":["T","AY1","M","AW1","T"],"ONE":["W","AH1","N"],"TWO":["T","UW1"],"THREE":["TH","R","IY1"],"FOUR":["F","AO1","R"],"FIVE":["F","AY1","V"],"SIX":["S","IH1","K","S"],"NINE":["N","AY1","N"],"TWENTY":["T","W","EH1","N","T","IY0"],"THIRTY":["TH","ER1","D","IY2"],"FORTY":["F","AO1","R","T","IY0"],"FIFTY":["F","IH1","F","T","IY0"]}
ACR={"SIM","TIMEOUT","UNDERSCORE"}

def spell(w):
    out=[]
    for c in w.upper():
        if c in LP: out+=LP[c]
    return out
def should_spell(raw):
    return len(raw)>1 and all('A'<=c<='Z' for c in raw) and raw.upper() not in ACR

def phones_for_word(raw):
    norm=raw.upper()
    if norm in OVR: return OVR[norm]
    if '-' in norm:
        out=[]
        for part in norm.split('-'):
            if not part: continue
            ph = OVR.get(part) or supp.get(part) or cmu.get(part) or spell(part)
            if ph: out+=ph
        if out: return out
    if norm in supp: return supp[norm]
    if should_spell(raw):
        s=spell(norm)
        if s: return s
    if norm in cmu: return cmu[norm]
    if '-' in norm:
        out=[]
        for part in norm.split('-'):
            if not part: continue
            ph = cmu.get(part) or spell(part)
            if ph: out+=ph
        if out: return out
    return spell(norm)

parser = argparse.ArgumentParser(description="Score English frontend pronunciation fixtures.")
parser.add_argument("fixture", type=Path, help="JSONL fixture containing text and golden_pinyin.")
args = parser.parse_args()
rows=[json.loads(l) for l in args.fixture.open(encoding='utf-8') if l.strip()]
tot=Counter(); ok=Counter(); fails={}
for r in rows:
    c=r['category']; g=r['golden_pinyin']; m=phones_for_word(r['text'])
    tot[c]+=1
    if m==g: ok[c]+=1
    else: fails.setdefault(c,[]).append((r['text'],' '.join(g),' '.join(m)))
print("=== 设备逻辑忠实模拟 vs golden ===")
for c in tot: print(f"{c:22} {ok[c]:3}/{tot[c]:3} = {100*ok[c]//tot[c]}%")
print(f"{'TOTAL':22} {sum(ok.values()):3}/{sum(tot.values()):3} = {100*sum(ok.values())//sum(tot.values())}%")
for c in fails:
    print(f"\n--- {c}: {len(fails[c])} 失败(前4)---")
    for t,g,m in fails[c][:4]: print(f"  {t:16} gold={g:34} dev={m}")
