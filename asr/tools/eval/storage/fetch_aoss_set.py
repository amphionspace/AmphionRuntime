"""从 AOSS 拉取 WenetSpeech-Chuan 真实四川话测试集（随机抽样）。

manifest 的 source 为 /workspace/data/...，AOSS 对象键为 audio-data/...，按此前缀映射。
"""
import concurrent.futures as cf, gzip, json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aossmin

SP=os.environ.get("SP", os.getcwd())
OUT=os.environ.get("OUT_DIR", f"{SP}/evaldata")
N=int(os.environ.get("SAMPLE_N","500"))
SEED=int(os.environ.get("SEED","20261026"))
W=int(os.environ.get("WORKERS","16"))

def key_of(src):
    assert src.startswith("/workspace/data/"), src
    return "audio-data/" + src[len("/workspace/data/"):]

def one(a):
    k,dst=a
    if os.path.exists(dst) and os.path.getsize(dst)>0: return 0
    for t in range(4):
        try:
            d=aossmin.request(key=k, want_bytes=True)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst,"wb").write(d); return len(d)
        except Exception as e:
            if t==3: print("  失败:",k,str(e)[:60]); return -1
            time.sleep(1.5*(t+1))

for split, n in (("test_easy", N), ("test_hard", 0)):   # hard 全取（1392 条 1.15h）
    rec={json.loads(l)["id"]: json.loads(l) for l in
         gzip.open(f"{SP}/chuan_data/{split}_recordings.jsonl.gz","rt",encoding="utf-8")}
    sup=[json.loads(l) for l in
         gzip.open(f"{SP}/chuan_data/{split}_supervisions.jsonl.gz","rt",encoding="utf-8")]
    random.seed(SEED); random.shuffle(sup)
    pick = sup if n == 0 else sup[:n]
    name=f"wenetspeech_chuan-{split}"
    base=f"{OUT}/{name}"
    os.makedirs(f"{base}/audio", exist_ok=True)
    rows=[]; jobs=[]
    for s in pick:
        r=rec[s["recording_id"]]
        src=r["sources"][0]["source"]
        fn=os.path.basename(src)
        jobs.append((key_of(src), f"{base}/audio/{fn}"))
        rows.append({"id":s["id"],"audio":f"audio/{fn}","duration":s["duration"],
                     "text":s["text"],"language":"zh",
                     "annotation":{"status":"verified","source":"official_human",
                                   "note":"WenetSpeech-Chuan 官方测试集，人工校验文本"},
                     "labels":{"accent":"四川话","scenario":split,
                               "reference_origin":"official_human","audio_origin":"real"}})
    open(f"{base}/manifest.jsonl","w",encoding="utf-8").write(
        "\n".join(json.dumps(x,ensure_ascii=False) for x in rows)+"\n")
    open(f"{base}/dataset.yaml","w",encoding="utf-8").write(
        f'annotation_status: "verified"\ncategory: "asr"\nchannels: 1\n'
        f'dataset_id: "wenetspeech_chuan"\nlanguage: "zh"\nsample_rate: 16000\n'
        f'samples: {len(rows)}\nhours: {sum(r["duration"] for r in rows)/3600:.4f}\n'
        f'version: "eval-20261012"\nsplit: "{split}"\n'
        f'title: "WenetSpeech-Chuan 四川话 {split}（随机抽样 {len(rows)} 条，seed {SEED}）"\n')
    b=f=0; t0=time.time()
    with cf.ThreadPoolExecutor(W) as ex:
        for i,v in enumerate(ex.map(one,jobs),1):
            if v<0: f+=1
            else: b+=v
            if i%200==0: print(f"    {i}/{len(jobs)} {b/1e6:.0f}MB", flush=True)
    print(f"  [{name}] {len(rows)} 条 / {sum(r['duration'] for r in rows)/3600:.2f}h / "
          f"{b/1e6:.0f}MB / {time.time()-t0:.0f}s / 失败 {f}", flush=True)
