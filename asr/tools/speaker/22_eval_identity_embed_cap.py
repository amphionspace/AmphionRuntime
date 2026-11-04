"""量"嵌入只取发言段前 N 秒"对准确率的影响。

动机：每段都切出整段音频（7 秒约 448 KB），143 段累计几十 MB 瞬时 ArkTS 堆，
真机实测内核 HWM 峰值比 model 模式高 141 MB。截断能同时降内存与原生算力。
"""
import itertools, json, os, wave, time
import numpy as np, sherpa_onnx

EVAL=os.path.expanduser("~/.cache/amphion-runtime/customer-inputs-20261030/dq5-diar-eval-20261027")
S=os.environ["SCRATCH"]
AUD=os.path.expanduser("~/Downloads/dingqiao-meeting-20260918/audio")
NAME={"meetingMinutes-20260918-100350-257":"meetingMinutes-20260918-100350-257.wav",
      "meetingMinutes-20260918-102010-230":"meetingMinutes-20260918-102010-230.wav",
      "meetingMinutes-20260918-111223-816":"meetingMinutes-20260918-111223-816.wav",
      "会议-离线-无角色4":"meeting-offline-unknown4.wav"}
ex=sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
    model="asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/campplus.onnx",
    num_threads=4, provider="cpu"))
TURNS=json.load(open(os.path.join(S,"sf_turns_perslot.json")))
refs={}
for line in open(os.path.join(EVAL,"reference-human-partial.rttm"), encoding="utf-8"):
    p=line.split(); refs.setdefault(p[1],[]).append(dict(begin=float(p[3]),dur=float(p[4]),spk=p[7]))
AUDIO={}
for rec,fn in NAME.items():
    w=wave.open(os.path.join(AUD,fn),'rb')
    AUDIO[rec]=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768.0
    w.close()
def embed(x):
    st=ex.create_stream(); st.accept_waveform(16000,x); st.input_finished()
    v=np.array(ex.compute(st),dtype=np.float64); n=np.linalg.norm(v)
    return v/n if n>0 else v
def assign(turns, embs, thr=0.45, ma=0.5, cap=4):
    cents=[];counts=[];out=[]
    for t,e in zip(turns,embs):
        if t["end"]-t["begin"] < ma: out.append(-1); continue
        if cents:
            sims=np.array([c@e for c in cents]); b=int(np.argmax(sims)); sc=float(sims[b])
        else: b,sc=-1,-1.0
        if b>=0 and sc>=thr: k=b
        elif len(cents)<cap: cents.append(e.copy()); counts.append(0); k=len(cents)-1
        else: k=b
        c=cents[k]*counts[k]+e; counts[k]+=1
        nn=np.linalg.norm(c); cents[k]=c/nn if nn>0 else c
        out.append(k)
    return out
composite=lambda l: l.count("_")>=3
def score(rows):
    so=sn=do=dn=0
    for rr in rows.values():
        for A,B in itertools.combinations(rr,2):
            if A[1]<0 or B[1]<0: continue
            if A[0]==B[0]:
                if composite(A[0]): continue
                sn+=1; so+=(A[1]==B[1])
            else: dn+=1; do+=(A[1]!=B[1])
    return so,sn,do,dn
print(f"{'嵌入取样上限':>12s} {'准确':>8s} {'样本总秒数':>11s} {'最大单段 KB':>12s} {'嵌入总耗时 s':>12s}")
for cap_s in (None, 6.0, 4.0, 3.0, 2.0, 1.0):
    rows={}; total=0.0; maxkb=0.0; t0=time.time()
    for rec in NAME:
        tl=TURNS[rec]; a=AUDIO[rec]; embs=[]
        for t in tl:
            b=int(t["begin"]*16000); e=int(t["end"]*16000)
            if cap_s is not None: e=min(e, b+int(cap_s*16000))
            seg=a[b:e]; total+=len(seg)/16000; maxkb=max(maxkb,len(seg)*4/1024)
            embs.append(embed(seg))
        ids=assign(tl,embs)
        rr=[]
        for r in refs.get(rec,[]):
            rb,re_=r["begin"],r["begin"]+r["dur"]; best,bov=-1,0.0
            for i,t in enumerate(tl):
                ov=max(0.0,min(re_,t["end"])-max(rb,t["begin"]))
                if ov>bov: bov,best=ov,i
            rr.append((r["spk"], ids[best] if best>=0 else -1))
        rows[rec]=rr
    s=score(rows); el=time.time()-t0
    label="不截断" if cap_s is None else f"{cap_s:.0f} s"
    print(f"{label:>12s} {f'{s[0]+s[2]}/{s[1]+s[3]}':>8s} {total:>11.0f} {maxkb:>12.0f} {el:>12.1f}")
