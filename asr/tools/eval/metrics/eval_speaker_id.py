"""开集说话人识别实测（按 speaker_id 全交叉配对，按拾音距离分档）。

试验：测试音频 i × 注册音频 j（i≠j 的不同条目），标签 = speaker_id 相同。
      注册音频各条自带 near/mid/far 三档，逐档独立评分。
开集：enrolled=False 的条目其 speaker 不在册，只能产生负例 —— 用于估计误接受。
打分：生产 ERes2Net + cosine（与 SDK 同 backend）。
"""
import json, os
from pathlib import Path
import numpy as np, soundfile as sf, sherpa_onnx

SP=Path(os.environ["SP"]); base=Path(os.environ["DS_ROOT"])/os.environ["DS_NAME"]
rows=[json.loads(l) for l in (base/"manifest.jsonl").open(encoding="utf-8")]
ex=sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=os.environ["VP_MODEL"], num_threads=4))
def emb(p):
    x,sr=sf.read(str(p),dtype="float32")
    if x.ndim>1: x=x[:,0]
    s=ex.create_stream(); s.accept_waveform(sr,x); s.input_finished()
    v=np.asarray(ex.compute(s),dtype=np.float64); return v/(np.linalg.norm(v)+1e-12)

items=[]
for r in rows:
    tp=base/r["audio"]
    if not tp.exists(): continue
    L=r.get("labels",{}); sa=r.get("speaker_audio") or {}
    en={}
    for d,rel in sa.items():
        p=base/rel
        if p.exists(): en[d]=emb(p)
    # 开集条目没有注册目录，仍须作为冒充者负例参与，不能跳过
    items.append({"id":r["id"],"spk":L.get("speaker_id") or L.get("enroll_group"),
                  "inset":bool(L.get("enrolled",True)),"scen":L.get("scenario",""),
                  "test":emb(tp),"enroll":en})
print(f"条目 {len(items)}，说话人 {len({i['spk'] for i in items})}，"
      f"在册 {sum(1 for i in items if i['inset'])}", flush=True)

def metrics(sc,lb):
    s=np.array(sc); l=np.array(lb)
    if l.sum()==0 or (1-l).sum()==0: return None
    o=np.argsort(-s); ls=l[o]; ss=s[o]
    P=int(l.sum()); N=len(l)-P
    tp=np.cumsum(ls); fp=np.cumsum(1-ls)
    frr=1-tp/P; far=fp/N
    i=int(np.argmin(np.abs(far-frr)))
    def at(x):
        j=np.searchsorted(far,x,side="right")-1; j=max(j,0); return float(frr[j]),float(ss[j])
    f1,t1=at(0.01); f01,t01=at(0.001)
    return {"eer":round(float((far[i]+frr[i])/2)*100,2),
            "accuracy_at_eer":round((1-float((far[i]+frr[i])/2))*100,2),
            "threshold":round(float(ss[i]),4),
            "frr_at_far_1pct":round(f1*100,2),"thr_far_1pct":round(t1,4),
            "frr_at_far_01pct":round(f01*100,2),
            "trials":len(l),"pos":P,"neg":N}

dists=sorted({d for i in items for d in i["enroll"]})
res={}
for d in dists:
    sc=[];lb=[]
    for a in items:
        for b in items:
            if a["id"]==b["id"] or d not in b["enroll"]: continue
            sc.append(float(a["test"]@b["enroll"][d]))
            lb.append(1 if (a["spk"]==b["spk"]) else 0)
    res[d]=metrics(sc,lb)
# 仅在册子集（闭集）作对照
res_inset={}
ins=[i for i in items if i["inset"]]
for d in dists:
    sc=[];lb=[]
    for a in ins:
        for b in ins:
            if a["id"]==b["id"] or d not in b["enroll"]: continue
            sc.append(float(a["test"]@b["enroll"][d])); lb.append(1 if a["spk"]==b["spk"] else 0)
    res_inset[d]=metrics(sc,lb)
out={"dataset":os.environ["DS_NAME"],"backend":"生产 ERes2Net + cosine",
     "open_set":res,"closed_set_inset_only":res_inset,
     "num_items":len(items),"num_speakers":len({i['spk'] for i in items})}
(SP/"evalout"/f"sid2_{os.environ['DS_NAME'].split('@')[0]}.json").write_text(
    json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"\n【开集（含 60 条不在册）】")
print(f"{'距离':<8}{'EER':>8}{'工作点准确率':>14}{'FAR=1%→FRR':>13}{'FAR=0.1%→FRR':>14}{'正/负例':>14}")
for d in ("near","mid","far"):
    if d not in res or res[d] is None: continue
    v=res[d]
    print(f"{d:<8}{v['eer']:>7.2f}%{v['accuracy_at_eer']:>13.2f}%{v['frr_at_far_1pct']:>12.2f}%"
          f"{v['frr_at_far_01pct']:>13.2f}%{v['pos']:>7}/{v['neg']}")
print(f"\n【闭集对照（仅 40 条在册）】")
for d in ("near","mid","far"):
    if d not in res_inset or res_inset[d] is None: continue
    v=res_inset[d]
    print(f"{d:<8}{v['eer']:>7.2f}%{v['accuracy_at_eer']:>13.2f}%{v['frr_at_far_1pct']:>12.2f}%"
          f"{v['frr_at_far_01pct']:>13.2f}%{v['pos']:>7}/{v['neg']}")
