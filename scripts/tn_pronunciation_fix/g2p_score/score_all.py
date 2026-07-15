import json,re,subprocess,sys,importlib
sys.path.insert(0,'.'); import frontend, g2p; importlib.reload(frontend); importlib.reload(g2p)
ZH="/private/tmp/claude-501/-Users-amphion-Desktop-work-reference/9cf64b2f-2741-48cc-8f55-27abd8a871b1/scratchpad/zh_tts_cur"
PIN=re.compile(r'^[a-z]+[0-6]$'); pins=lambda l:[x for x in l if PIN.match(x)]
B="/Users/amphion/Desktop/work/reference/AmphionRuntime/tts_tn_bugfix/"
SETS=[("round15",B+"pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl"),
      ("hard500",B+"github-tts-hardcases-500.jsonl"),
      ("addl500",B+"github-tts-hardcases-additional-500.jsonl")]
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
    for n,p in SETS:
        ok,t,bycat,_=score(p)
        print(f"{n}: {ok}/{t} = {100*ok//t}%   " + " ".join(f"{c.split('-')[0]}:{v[0]}/{v[1]}" for c,v in sorted(bycat.items())))
