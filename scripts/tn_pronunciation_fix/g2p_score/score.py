import json,re,sys,subprocess
sys.path.insert(0,'.'); import g2p
ZH="/private/tmp/claude-501/-Users-amphion-Desktop-work-reference/9cf64b2f-2741-48cc-8f55-27abd8a871b1/scratchpad/zh_tts_cur"
PIN=re.compile(r'^[a-z]+[0-6]$')
def pins(l): return [x for x in l if PIN.match(x)]
def tn(texts):
    p=subprocess.run([ZH],input=('\n'.join(texts)+'\n').encode(),capture_output=True)
    return p.stdout.decode('utf-8',errors='replace').split('\n')
def pipeline_pinyin(texts):
    outs=tn(texts)
    return [pins(g2p.text_to_pinyin(o)) for o in outs[:len(texts)]]
if __name__=="__main__":
    path=sys.argv[1]
    rows=[json.loads(l) for l in open(path,encoding='utf-8') if l.strip()]
    # zh only (skip en-core), and skip entries whose golden has ARPABET (uppercase) letters we don't model
    def is_scorable(r):
        if r.get('category')=='en-core': return False
        g=r['golden_pinyin']
        up=sum(1 for x in g if re.match(r'^[A-Z]',x))
        return up==0
    rows=[r for r in rows if is_scorable(r)]
    texts=[' '.join(r['text'].split()) for r in rows]
    preds=pipeline_pinyin(texts)
    ok=0
    fails=[]
    for r,p in zip(rows,preds):
        g=pins(r['golden_pinyin'])
        if p==g: ok+=1
        else: fails.append((r,p,g))
    print(f"{path.split('/')[-1]}: scorable-zh {len(rows)}, my-pipeline PASS {ok} = {100*ok//max(1,len(rows))}%")
    return_fails=fails
    import random
    for r,p,g in fails[:6]:
        print("  FAIL:",r['text'][:40])
        print("    mine :"," ".join(p[:16]))
        print("    gold :"," ".join(g[:16]))
