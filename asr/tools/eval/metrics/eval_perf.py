"""时延 / 计算量 / 内存 A/B。

指标：
  RTF                 解码耗时 / 音频时长（单进程、固定线程数）
  首个非空 partial 时延  从开始喂入到第一次拿到非空结果的墙钟时间
  endpoint→final 时延   检出 endpoint 到该段 final 可取的时间
  尾包时延             input_finished 到最后一次 decode 完成
  CPU 秒 / 音频秒       功耗代理（能耗 ∝ CPU 时间；同架构下可直接比较）
  峰值 RSS            进程常驻内存峰值
按 20ms 实时节奏喂入，与 SDK 一致。
"""
import json, os, resource, sys, time
from pathlib import Path
import numpy as np, soundfile as sf, sherpa_onnx
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_layout import transducer_paths


SP=Path(os.environ["SP"]); M=os.environ["MODELS"]; TAG=os.environ["TAG"]
files=json.loads(os.environ["FILES"])
THREADS=int(os.environ.get("THREADS","2"))
presets=[l.strip() for l in (SP/"hw_full_nouser.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
pbuf="\n".join(presets)
mp=transducer_paths(M)
enc=mp["encoder"]; dec=mp["decoder"]; joi=mp["joiner"]
t0=time.perf_counter()
r=sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=mp["tokens"], encoder=enc, decoder=dec, joiner=joi,
    num_threads=THREADS, decoding_method="modified_beam_search", max_active_paths=8,
    hotwords_score=1.0, modeling_unit="bbpe", bpe_vocab=mp["bpe_vocab"],
    enable_endpoint_detection=True)
load_ms=(time.perf_counter()-t0)*1000

def cpu_sec():
    u=resource.getrusage(resource.RUSAGE_SELF)
    c=resource.getrusage(resource.RUSAGE_CHILDREN)
    return (u.ru_utime+u.ru_stime+c.ru_utime+c.ru_stime)

rows=[]
STEP=int(16000*0.02)   # 20ms
for f in files:
    x,sr=sf.read(f, dtype="float32")
    if x.ndim>1: x=x[:,0]
    dur=len(x)/16000
    s=r.create_stream(pbuf)
    c0=cpu_sec(); w0=time.perf_counter()
    first_partial=None; ep_lat=[]
    last_ep_at=None
    for i in range(0,len(x),STEP):
        s.accept_waveform(16000, x[i:i+STEP])
        while r.is_ready(s): r.decode_stream(s)
        if first_partial is None and r.get_result(s):
            first_partial=(time.perf_counter()-w0)*1000
        if r.is_endpoint(s):
            if last_ep_at is None: last_ep_at=time.perf_counter()
            txt=r.get_result(s)
            if last_ep_at is not None:
                ep_lat.append((time.perf_counter()-last_ep_at)*1000); last_ep_at=None
            r.reset(s)
    tail0=time.perf_counter()
    s.accept_waveform(16000, np.zeros(8000, dtype=np.float32))
    s.input_finished()
    while r.is_ready(s): r.decode_stream(s)
    tail_ms=(time.perf_counter()-tail0)*1000
    wall=time.perf_counter()-w0; cpu=cpu_sec()-c0
    rows.append({"file":os.path.basename(f),"dur":round(dur,2),
                 "rtf":round(wall/dur,4),"cpu_per_audio":round(cpu/dur,4),
                 "first_partial_ms":None if first_partial is None else round(first_partial,1),
                 "tail_ms":round(tail_ms,1),
                 "endpoint_to_final_ms":[round(v,1) for v in ep_lat]})
peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e6  # macOS: bytes
def med(v): 
    v=[x for x in v if x is not None]
    return None if not v else round(float(np.median(v)),2)
def p95(v):
    v=[x for x in v if x is not None]
    return None if not v else round(float(np.percentile(v,95)),2)
eps=[v for rr in rows for v in rr["endpoint_to_final_ms"]]
out={"tag":TAG,"models":M,"threads":THREADS,"n":len(rows),
     "load_ms":round(load_ms,1),
     "audio_sec":round(sum(rr["dur"] for rr in rows),1),
     "rtf_median":med([rr["rtf"] for rr in rows]),"rtf_p95":p95([rr["rtf"] for rr in rows]),
     "cpu_per_audio_median":med([rr["cpu_per_audio"] for rr in rows]),
     "first_partial_ms_median":med([rr["first_partial_ms"] for rr in rows]),
     "first_partial_ms_p95":p95([rr["first_partial_ms"] for rr in rows]),
     "tail_ms_median":med([rr["tail_ms"] for rr in rows]),
     "tail_ms_p95":p95([rr["tail_ms"] for rr in rows]),
     "endpoint_to_final_ms_median":med(eps),"endpoint_to_final_ms_p95":p95(eps),
     "endpoint_count":len(eps),
     "peak_rss_mb":round(peak_rss,1),"items":rows}
(SP/"about"/f"perf_{TAG}.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"[{TAG}] n={out['n']} 音频 {out['audio_sec']}s  加载 {out['load_ms']}ms")
print(f"  RTF 中位 {out['rtf_median']}  P95 {out['rtf_p95']}")
print(f"  CPU秒/音频秒 {out['cpu_per_audio_median']}  （功耗代理）")
print(f"  首个partial 中位 {out['first_partial_ms_median']}ms  P95 {out['first_partial_ms_p95']}ms")
print(f"  endpoint→final 中位 {out['endpoint_to_final_ms_median']}ms  P95 {out['endpoint_to_final_ms_p95']}ms  (n={out['endpoint_count']})")
print(f"  尾包 中位 {out['tail_ms_median']}ms  P95 {out['tail_ms_p95']}ms")
print(f"  峰值 RSS {out['peak_rss_mb']} MB")
