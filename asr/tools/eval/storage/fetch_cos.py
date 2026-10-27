"""并行下载 COS 评测集（manifest + 全部音频），支持续传与校验。"""
import concurrent.futures as cf, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cosmin

ROOT = os.environ.get("EVAL_ROOT") or os.path.join(
    os.environ.get("SP", os.getcwd()), "evaldata")
P = "amphion-eval/datasets/asr/"
WORKERS = int(os.environ.get("FETCH_WORKERS", "12"))

def fetch_one(args):
    key, dest, size = args
    if os.path.exists(dest) and (size is None or os.path.getsize(dest) == size):
        return 0
    for attempt in range(4):
        try:
            n = cosmin.get(key, dest)
            return n
        except Exception as e:
            if attempt == 3:
                return -1
            time.sleep(1.5 * (attempt + 1))
    return -1

def fetch_dataset(name):
    base = f"{P}{name}/"
    out = os.path.join(ROOT, name)
    os.makedirs(out, exist_ok=True)
    for meta in ("dataset.yaml", "manifest.jsonl"):
        d = os.path.join(out, meta)
        if not os.path.exists(d):
            cosmin.get(base + meta, d)
    rows = [json.loads(l) for l in open(os.path.join(out, "manifest.jsonl"), encoding="utf-8")]
    _, files = cosmin.listdir(base + "audio/", delimiter="")
    sizes = {k: s for k, s in files}
    jobs = []
    for r in rows:
        key = base + r["audio"]
        jobs.append((key, os.path.join(out, r["audio"]), sizes.get(key)))
    done = bytes_ = fail = 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for n in ex.map(fetch_one, jobs):
            done += 1
            if n < 0: fail += 1
            else: bytes_ += n
            if done % 400 == 0:
                el = time.time() - t0
                print(f"    {name}: {done}/{len(jobs)}  {bytes_/1e6:.0f}MB  "
                      f"{bytes_/1e6/max(el,1):.1f}MB/s  失败{fail}", flush=True)
    el = time.time() - t0
    print(f"  [{name}] {done} 条，{bytes_/1e6:.0f}MB，{el:.0f}s，"
          f"{bytes_/1e6/max(el,1):.1f}MB/s，失败 {fail}", flush=True)
    return {"name": name, "n": done, "bytes": bytes_, "fail": fail, "sec": round(el, 1)}

if __name__ == "__main__":
    res = [fetch_dataset(n) for n in sys.argv[1:]]
    print(json.dumps(res, ensure_ascii=False))
