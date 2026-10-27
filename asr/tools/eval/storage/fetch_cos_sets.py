import concurrent.futures as cf, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cosmin
ROOT=os.environ.get("EVAL_ROOT") or os.path.join(
    os.environ.get("SP", os.getcwd()), "evaldata")
W=int(os.environ.get("FETCH_WORKERS","16"))
def one(a):
    key,dest,size=a
    if os.path.exists(dest) and (size is None or os.path.getsize(dest)==size): return 0
    for t in range(4):
        try: return cosmin.get(key,dest)
        except Exception:
            if t==3: return -1
            time.sleep(1.5*(t+1))
def ds(cat,name):
    base=f"amphion-eval/datasets/{cat}/{name}/"
    out=os.path.join(ROOT,cat,name); os.makedirs(out,exist_ok=True)
    for m in ("dataset.yaml","manifest.jsonl"):
        p=os.path.join(out,m)
        if not os.path.exists(p):
            try: cosmin.get(base+m,p)
            except Exception as e: print(f"  [{name}] {m} 缺: {e}"); 
    mp=os.path.join(out,"manifest.jsonl")
    if not os.path.exists(mp): print(f"  [{name}] 无 manifest，跳过"); return
    rows=[json.loads(l) for l in open(mp,encoding="utf-8")]
    _,files=cosmin.listdir(base+"audio/",delimiter="")
    sizes={k:s for k,s in files}
    jobs=[(base+r["audio"], os.path.join(out,r["audio"]), sizes.get(base+r["audio"])) for r in rows if r.get("audio")]
    b=f=0; t0=time.time()
    with cf.ThreadPoolExecutor(W) as ex:
        for n in ex.map(one,jobs):
            if n<0: f+=1
            else: b+=n
    print(f"  [{cat}/{name}] {len(jobs)} 条 {b/1e6:.0f}MB {time.time()-t0:.0f}s 失败{f}", flush=True)
if __name__=="__main__":
    for cat in sys.argv[1:]:
        d,_=cosmin.listdir(f"amphion-eval/datasets/{cat}/")
        print(f"=== {cat} ===", flush=True)
        for p in d: ds(cat, p.rstrip('/').split('/')[-1])
