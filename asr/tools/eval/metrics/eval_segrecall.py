"""片段召回实测。

定义（本测试采用，需与客户确认）：
  片段召回 = 被识别输出覆盖的参考语音段数 / 参考语音段总数
  「覆盖」= 该段 [start,end] 内（含 ±collar）至少落入一个识别 token 的时间戳。
同时给出时长加权召回 = 被覆盖段的总时长 / 参考段总时长。

参考段来自 AliMeeting 官方说话人时间轴（verified）；重叠段按独立段计。
流式解码按 20ms 实时喂入，endpoint 后继续同一 stream，token 时间戳用 start_time+timestamps。
"""
import argparse, json, os, re
from pathlib import Path
import numpy as np, soundfile as sf, sherpa_onnx
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_layout import transducer_paths


ap=argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--dataset", required=True)
ap.add_argument("--models", required=True)
ap.add_argument("--presets", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--collar", type=float, default=0.25)
ap.add_argument("--chunk-ms", type=int, default=100)
a=ap.parse_args()

base=Path(a.root)/a.dataset
rows=[json.loads(l) for l in (base/"manifest.jsonl").open(encoding="utf-8")]
presets=[l.strip() for l in Path(a.presets).read_text(encoding="utf-8").splitlines() if l.strip()]
pbuf="\n".join(presets)
M=a.models
_mp = transducer_paths(M)
r=sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=_mp["tokens"], encoder=_mp["encoder"], decoder=_mp["decoder"],
    joiner=_mp["joiner"], num_threads=2, decoding_method="modified_beam_search",
    max_active_paths=8, hotwords_score=1.0, modeling_unit="bbpe", bpe_vocab=_mp["bpe_vocab"],
    enable_endpoint_detection=True)

SEG=re.compile(r'\[(S\d+)\]\[([\d.]+)-([\d.]+)\]')
def refsegs(t): return [(m.group(1), float(m.group(2)), float(m.group(3))) for m in SEG.finditer(t or "")]

def decode_with_times(x):
    """流式喂入，收集全程 token 绝对时间戳（跨 endpoint 累加 segment 偏移）。"""
    s=r.create_stream(pbuf)
    step=int(16000*a.chunk_ms/1000)
    times=[]; texts=[]
    def harvest():
        st=r.start_time(s); ts=r.timestamps(s); tk=r.tokens(s)
        if ts: times.extend(st+float(v) for v in ts)
        t=r.get_result(s)
        if t: texts.append(t)
    for i in range(0,len(x),step):
        s.accept_waveform(16000, x[i:i+step])
        while r.is_ready(s): r.decode_stream(s)
        if r.is_endpoint(s):
            harvest(); r.reset(s)
    s.accept_waveform(16000, np.zeros(8000, dtype=np.float32))
    s.input_finished()
    while r.is_ready(s): r.decode_stream(s)
    harvest()
    return sorted(times), "".join(texts)

tot=cov=0; dur_tot=dur_cov=0.0
per=[]
for row in rows:
    f=base/row["audio"]
    if not f.exists(): continue
    x,sr=sf.read(str(f), dtype="float32")
    if x.ndim>1: x=x[:,0]
    assert sr==16000, sr
    segs=refsegs(row.get("text"))
    if not segs: continue
    times,txt=decode_with_times(x)
    T=np.array(times) if times else np.array([])
    c=0; dc=0.0
    for spk,st,en in segs:
        hit = bool(T.size) and bool(((T>=st-a.collar)&(T<=en+a.collar)).any())
        c+=int(hit); dc+= (en-st) if hit else 0.0
    tot+=len(segs); cov+=c
    dtot=sum(en-st for _,st,en in segs)
    dur_tot+=dtot; dur_cov+=dc
    per.append({"id":row["id"],"segments":len(segs),"covered":c,
                "recall":round(c/len(segs),4),
                "dur_recall":round(dc/dtot,4) if dtot else None,
                "tokens":len(times),"duration":row.get("duration")})
    print(f"  {row['id']:<44} 段 {len(segs):>3} 覆盖 {c:>3} 召回 {c/len(segs)*100:6.2f}%  token {len(times)}", flush=True)

out={"dataset":a.dataset,"collar":a.collar,
     "segment_recall":round(cov/tot,4) if tot else None,
     "duration_weighted_recall":round(dur_cov/dur_tot,4) if dur_tot else None,
     "total_segments":tot,"covered_segments":cov,
     "total_speech_sec":round(dur_tot,1),"items":per}
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"\n[{a.dataset}]  片段召回 {cov/tot*100:.2f}%（{cov}/{tot} 段）  "
      f"时长加权召回 {dur_cov/dur_tot*100:.2f}%  参考语音 {dur_tot:.0f}s")
