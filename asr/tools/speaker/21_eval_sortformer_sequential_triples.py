import os, sys, glob, wave, json
import numpy as np
from collections import defaultdict
sys.path.insert(0, os.path.expanduser("~/.cache/amphion-runtime/customer-inputs-20261030/dq5-diar-eval-20261027"))
PKG = os.environ["SF_PKG"]
S = "/private/tmp/claude-501/-Users-momo/6ed1db33-51ea-448e-8da5-1a9b589c932b/scratchpad"
import sf_infer
by=defaultdict(list)
for f in sorted(glob.glob(f"{S}/aishell16k/*.wav")): by[os.path.basename(f)[:7]].append(f)
spks=[k for k,v in by.items() if len(v)>=6]
SEC=float(os.environ.get("SEC","10"))
def cat(spk, sec):
    buf=[]
    for f in by[spk]:
        w=wave.open(f,'rb'); buf.append(np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16)); w.close()
        if sum(len(b) for b in buf)/16000 >= sec: break
    return np.concatenate(buf)[:int(sec*16000)]
m = sf_infer.Sortformer(PKG, encoder="int8ort1163", threads=8)
rng=np.random.default_rng(7)
ok=0; rows=[]
N=int(os.environ.get("N","10"))
for t in range(N):
    trio=list(rng.choice(spks, 3, replace=False))
    segs=[cat(s, SEC) for s in trio]
    audio=np.concatenate(segs).astype(np.float32)/32768.0
    probs=m.run(audio); act=probs>=0.5
    doms=[]
    for i in range(3):
        lo,hi=int(i*SEC*100), min(int((i+1)*SEC*100), probs.shape[0])
        per=act[lo:hi].sum(axis=0)/100.0
        doms.append(int(np.argmax(per)) if per.sum()>0 else -1)
    distinct=len(set(d for d in doms if d>=0))
    good = distinct==3
    ok += good
    rows.append((trio, doms, distinct, good))
    print(f"  {t+1:2d}. {'/'.join(trio)}  槽位={doms}  不同角色数={distinct}  {'✅' if good else '❌'}")
print(f"\n每人 {SEC:.0f} 秒、三人依次：{ok}/{N} 组正确分出三个角色（{ok/N*100:.0f}%）")
