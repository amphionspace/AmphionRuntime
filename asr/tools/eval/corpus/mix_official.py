"""把官方评测集按客户 5 档 SNR 加噪，供逐档实测（替代系数外推）。

噪声与 SNR 定义沿用前轮：babble=20 位 AISHELL-3 说话人叠加；traffic=合成低频；
SNR 按有效语音段 RMS 定义。档位对齐客户表：安静≥20 / 轻度10~20 / 中度5~10 / 重度0~5。
"""
import gzip, json, os, random, sys
from pathlib import Path
import numpy as np, soundfile as sf

SP = Path(os.environ["SP"]); SR = 16000
random.seed(20261026); np.random.seed(20261026)

def rms(x): return float(np.sqrt(np.mean(x**2)+1e-12))
def speech_rms(x):
    fl=int(0.025*SR); n=len(x)//fl
    if n==0: return rms(x)
    f=x[:n*fl].reshape(n,fl); e=np.sqrt(np.mean(f**2,axis=1)+1e-12)
    thr=max(e.max()*0.1,np.percentile(e,60)*0.5); keep=e>=thr
    if not keep.any(): keep=e>=np.percentile(e,50)
    return float(np.sqrt(np.mean(f[keep]**2)+1e-12))

# 复刻噪声（与前轮同构造、同种子族）
CL = SP/"snrsets"/"clean"
pool = sorted(CL.glob("*.wav"))
need = int(60*SR)
babble = np.zeros(need); used=0
for p in pool:
    if used>=20: break
    x,_ = sf.read(str(p), dtype="float64")
    if len(x)<SR: continue
    t=np.tile(x,int(np.ceil(need/len(x))))[:need]
    babble += t/(speech_rms(t)+1e-12); used+=1
babble/= (rms(babble)+1e-12)
w=np.random.randn(need); W=np.fft.rfft(w); fr=np.fft.rfftfreq(need,1/SR)
shape=1.0/np.sqrt(1.0+(fr/180.0)**2); shape[fr<20]=0.0
traffic=np.fft.irfft(W*shape,n=need); traffic/=(rms(traffic)+1e-12)
print(f"噪声就绪（babble 用 {used} 位说话人）", flush=True)

LEVELS=[("quiet",20.0),("light",15.0),("medium",7.0),("heavy",3.0)]
def mix(x,nz,snr):
    if len(nz)<len(x): nz=np.tile(nz,int(np.ceil(len(x)/len(nz))))
    off=random.randrange(0,len(nz)-len(x)+1)
    n=nz[off:off+len(x)]
    return x + n*((speech_rms(x)/(10**(snr/20.0)))/(rms(n)+1e-12))

SRC = SP/"evaldata"
for spec in sys.argv[1:]:
    name, _, samp = spec.partition(":")
    samp = int(samp) if samp else 0
    base = SRC/name
    rows=[json.loads(l) for l in (base/"manifest.jsonl").open(encoding="utf-8")]
    if samp and samp < len(rows):
        step=len(rows)/samp; rows=[rows[int(i*step)] for i in range(samp)]
    out = SP/"officialsnr"/name
    (out/"manifest.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (out/"manifest.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows)+"\n",encoding="utf-8")
    if (base/"dataset.yaml").exists():
        (out/"dataset.yaml").write_text((base/"dataset.yaml").read_text(encoding="utf-8"),encoding="utf-8")
    print(f"{name}: {len(rows)} 条 -> 8 个噪声变体", flush=True)
    for nk,nz in (("babble",babble),("traffic",traffic)):
        for lk,snr in LEVELS:
            d=out/f"{nk}_{lk}"
            for r in rows:
                dst=d/r["audio"]; dst.parent.mkdir(parents=True,exist_ok=True)
                if dst.exists(): continue
                x,sr=sf.read(str(base/r["audio"]),dtype="float64")
                if x.ndim>1: x=x[:,0]
                if sr!=SR: continue
                y=mix(x,nz,snr); m=np.max(np.abs(y))
                if m>0.999: y=y*(0.999/m)
                sf.write(str(dst),y.astype(np.float32),SR,subtype="PCM_16")
            print(f"  {nk}_{lk} ok", flush=True)
print("完成", flush=True)
