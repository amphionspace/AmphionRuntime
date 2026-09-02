import argparse,json,re,subprocess,sys,importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent)); import frontend, g2p; importlib.reload(frontend); importlib.reload(g2p)
REPO_ROOT = Path(__file__).resolve().parents[5]
ZH = __import__("os").environ.get("ZH_TTS") or str(
    REPO_ROOT / "tts/training/dingqiao_lits/build/host-tn/zh_tts"
)
PIN=re.compile(r'^[a-z]+[0-6]$'); pins=lambda l:[x for x in l if PIN.match(x)]
DEFAULT_SET = REPO_ROOT / "tts/android/testdata/dingqiao_batch_cases/pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl"
def score(path,show_fails=0,cat=None):
    rows=[json.loads(l) for l in open(path,encoding='utf-8') if l.strip()]
    rows=[r for r in rows if r.get('category')!='en-core' and not any(re.match(r'^[A-Z]',x) for x in r['golden_pinyin'])]
    if cat: rows=[r for r in rows if r['category']==cat]
    prepped=[frontend.frontend_prepare(r['text']) for r in rows]
    outs=subprocess.run([ZH],input=('\n'.join(prepped)+'\n').encode(),capture_output=True).stdout.decode('utf-8','replace').split('\n')
    ok=0; bycat={}; fails=[]
    for r,o in zip(rows,outs):
        g=pins(r['golden_pinyin']); m=pins(g2p.text_to_pinyin(o)); p=(m==g)
        c=r['category']; bycat.setdefault(c,[0,0]); bycat[c][1]+=1; bycat[c][0]+=p; ok+=p
        if not p: fails.append((r,frontend.frontend_prepare(r['text']),o,g,m))
    return ok,len(rows),bycat,fails
if __name__=="__main__":
    parser = argparse.ArgumentParser(description="Score TN + G2P fixtures.")
    parser.add_argument(
        "fixtures",
        nargs="*",
        type=Path,
        default=[DEFAULT_SET],
        help="JSONL fixture paths; defaults to the tracked round15 set.",
    )
    args = parser.parse_args()
    for p in args.fixtures:
        n = p.stem
        ok,t,bycat,_=score(p)
        print(f"{n}: {ok}/{t} = {100*ok//t}%   " + " ".join(f"{c.split('-')[0]}:{v[0]}/{v[1]}" for c,v in sorted(bycat.items())))
