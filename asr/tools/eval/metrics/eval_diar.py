"""AliMeeting（verified 人工金标）角色分离 DER 实测。

参考：manifest.text 的官方说话人时间轴 [S1][9.35-18.16]，含重叠。
评分：10ms 栅格、250ms collar、枚举全排列取最优标号映射。
     重叠帧（参考同时 >1 人）单独统计并排除在 DER 之外（标准「DER excluding overlap」口径）。
管线：我们的 pyannote 分割模型 + 我们的 ERes2Net embedding + 上游 FastClustering。
     注意：产品 Community-1 用 PLDA/VBx 聚类且 embedding 走 wespeaker encoder+pool，
     二者在宿主侧不可运行，故本结果是「同分割模型、异聚类/异 embedding」口径。
"""
import itertools, json, os, re, sys
from pathlib import Path
import numpy as np, soundfile as sf, sherpa_onnx

SP=Path(os.environ["SP"]); SEG=os.environ["SEG_MODEL"]; EMB=os.environ["EMB_MODEL"]
base=Path(os.environ["DS_ROOT"])/os.environ["DS_NAME"]
rows=[json.loads(l) for l in (base/"manifest.jsonl").open(encoding="utf-8")]
COLLAR=0.25; STEP=0.01
PAT=re.compile(r'\[(S\d+)\]\[([\d.]+)-([\d.]+)\]')

def der(ref, hyp, dur):
    n=int(dur/STEP)+1
    spk=sorted({s for s,_,_ in ref})
    R=np.zeros((len(spk),n),dtype=bool)
    idx={s:i for i,s in enumerate(spk)}
    for s,a,b in ref:
        R[idx[s], max(0,int(a/STEP)):min(n,int(b/STEP))]=True
    cnt=R.sum(axis=0)
    H=np.full(n,-1,dtype=np.int64)
    for s in hyp:
        H[max(0,int(s["start"]/STEP)):min(n,int(s["end"]/STEP))]=s["speaker"]
    mask=np.ones(n,dtype=bool)
    for s,a,b in ref:
        for t in (a,b):
            mask[max(0,int((t-COLLAR)/STEP)):min(n,int((t+COLLAR)/STEP))]=False
    single = mask & (cnt==1)
    ov_frames = int((mask & (cnt>1)).sum())
    if single.sum()==0: return None,None,None,None
    Rs=np.argmax(R,axis=0)           # 单人帧的参考说话人
    hs=sorted(set(H[single].tolist())-{-1})
    co={}
    for ri in range(len(spk)):
        for h in hs:
            co[(ri,h)]=int(((Rs==ri)&(H==h)&single).sum())
    best=0
    if hs:
        for perm in itertools.permutations(hs, min(len(spk),len(hs))):
            best=max(best, sum(co[(i,perm[i])] for i in range(len(perm))))
    tot=int(single.sum())
    return 1-best/tot, tot, ov_frames, len(spk)

out=[]
for row in rows:
    f=base/row["audio"]
    if not f.exists(): continue
    ref=[(m.group(1),float(m.group(2)),float(m.group(3))) for m in PAT.finditer(row.get("text") or "")]
    if not ref: continue
    nspk=len({s for s,_,_ in ref})
    cfg=sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=SEG), num_threads=4),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=EMB, num_threads=4),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=nspk),
        min_duration_on=0.3, min_duration_off=0.5)
    sd=sherpa_onnx.OfflineSpeakerDiarization(cfg)
    x,sr=sf.read(str(f), dtype="float32")
    if x.ndim>1: x=x[:,0]
    res=sd.process(x).sort_by_start_time()
    hyp=[{"start":s.start,"end":s.end,"speaker":s.speaker} for s in res]
    d,scored,ovf,nref=der(ref,hyp,row["duration"])
    nh=len({s["speaker"] for s in hyp})
    out.append({"id":row["id"],"ref_speakers":nref,"hyp_speakers":nh,
                "der":None if d is None else round(d,4),
                "scored_sec":round(scored*STEP,1) if scored else None,
                "overlap_sec":round(ovf*STEP,1) if ovf is not None else None,
                "duration":row["duration"],"segments":len(ref)})
    print(f"  {row['id'][-26:]:<28} 参考{nref}人 输出{nh}人  DER "
          f"{'—' if d is None else f'{d*100:6.2f}%'}  计分{scored*STEP:.0f}s 重叠{ovf*STEP:.0f}s", flush=True)

valid=[o for o in out if o["der"] is not None]
byn={}
for o in valid: byn.setdefault(o["ref_speakers"],[]).append(o)
summary={"dataset":os.environ["DS_NAME"],"collar":COLLAR,
         "pipeline":"our pyannote + our ERes2Net + upstream FastClustering",
         "note":"DER excluding overlap；产品 Community-1 用 PLDA/VBx，宿主不可运行",
         "overall_der":round(float(np.mean([o['der'] for o in valid])),4) if valid else None,
         "by_speakers":{str(k):{"n":len(v),
                                "mean_der":round(float(np.mean([o['der'] for o in v])),4),
                                "accuracy":round(1-float(np.mean([o['der'] for o in v])),4),
                                "der_min":round(min(o['der'] for o in v),4),
                                "der_max":round(max(o['der'] for o in v),4)} for k,v in sorted(byn.items())},
         "speaker_count_correct":sum(1 for o in valid if o["hyp_speakers"]==o["ref_speakers"]),
         "items":out}
(SP/"evalout"/f"diar_{os.environ['DS_NAME'].split('@')[0]}.json").write_text(
    json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"\n整体平均 DER {summary['overall_der']*100:.2f}%  -> 准确率 {(1-summary['overall_der'])*100:.2f}%")
print(f"说话人数判对 {summary['speaker_count_correct']}/{len(valid)}")
for k,v in summary["by_speakers"].items():
    print(f"  {k} 人（{v['n']} 条）DER {v['mean_der']*100:.2f}% -> 准确率 {v['accuracy']*100:.2f}%"
          f"  区间 {v['der_min']*100:.1f}~{v['der_max']*100:.1f}%")
