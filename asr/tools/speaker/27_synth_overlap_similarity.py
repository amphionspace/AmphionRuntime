"""补两条合成轴：重叠讲话（标称容量内）与说话人音色相似度分层。

为什么要这两轴：
- 26_ 的合成集**完全没有重叠**（轮次间留 0.3 s 空隙），而重叠是 AISHELL-4 上唯一
  干净的单调恶化轴（跳变/人 3.2→12.1→18.5）。那份数据全是 5~7 人，所以标称容量内
  （2/3/4 人）的重叠行为此前没有任何数据。
- 26_ 的组内极差（最大 61pp）大于轴间差异，我据此推断"失败由音色是否相近主导"。
  那只是推断。本脚本按 CAM++ 成对相似度把三人组分成相远/中/相近三档，直接测它。
"""
import argparse
import glob
import itertools
import json
import os
import wave
from collections import defaultdict

import numpy as np

SR = 16000


def load_pool(aishell_dir, min_clips=4):
    by = defaultdict(list)
    for f in sorted(glob.glob(f"{aishell_dir}/*.wav")):
        by[os.path.basename(f)[:7]].append(f)
    return {k: v for k, v in by.items() if len(v) >= min_clips}


def read_wav(path):
    w = wave.open(path, "rb")
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    w.close()
    return x


def speaker_audio(files, seconds, rng):
    need = int(seconds * SR)
    order = list(files)
    rng.shuffle(order)
    out, total, i = [], 0, 0
    while total < need and i <= len(order) * 4:
        x = read_wav(order[i % len(order)])
        out.append(x)
        total += len(x)
        i += 1
    cat = np.concatenate(out)
    if len(cat) < need:
        cat = np.tile(cat, int(np.ceil(need / len(cat))))
    return cat[:need]


def speaker_embeddings(pool, model, seconds=6.0):
    """每个说话人一条 CAM++ 嵌入（取其前 seconds 秒拼接），L2 归一化。"""
    import sherpa_onnx
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model, num_threads=4, provider="cpu"))
    out = {}
    for spk, files in pool.items():
        buf, total = [], 0
        for f in files:
            x = read_wav(f)
            buf.append(x)
            total += len(x)
            if total >= seconds * SR:
                break
        x = np.concatenate(buf)[:int(seconds * SR)].astype(np.float32) / 32768.0
        st = ex.create_stream()
        st.accept_waveform(SR, x)
        st.input_finished()
        v = np.array(ex.compute(st), dtype=np.float64)
        n = np.linalg.norm(v)
        out[spk] = v / n if n > 0 else v
    return out


def pick_triples(emb, rng, per_band=5, size=3, candidates=4000):
    """按组内**最大**成对相似度分三档抽样。

    用最大值而不是均值：身份合并是两两之间发生的，一对过近就足以出错。
    """
    spks = sorted(emb)
    seen, scored = set(), []
    for _ in range(candidates):
        g = tuple(sorted(rng.choice(spks, size, replace=False)))
        if g in seen:
            continue
        seen.add(g)
        s = max(float(emb[a] @ emb[b]) for a, b in itertools.combinations(g, 2))
        scored.append((s, g))
    scored.sort()
    vals = [s for s, _ in scored]
    lo, hi = np.percentile(vals, [33, 67])
    bands = {"相远": [(s, g) for s, g in scored if s <= lo],
             "中": [(s, g) for s, g in scored if lo < s < hi],
             "相近": [(s, g) for s, g in scored if s >= hi]}

    def closest_pair(g):
        return max(itertools.combinations(g, 2), key=lambda p: emb[p[0]] @ emb[p[1]])

    out = {}
    for name, cand in bands.items():
        # 从档位边界往档内走：相近档要最像的，另两档要最不像的
        ordered = cand[::-1] if name == "相近" else cand
        # 同一档内禁止复用"最近对"，否则 5 个样本其实是同一个难点的 5 次重复，没有独立性
        used_pairs, take, sims = set(), [], []
        for s, g in ordered:
            pair = tuple(sorted(closest_pair(g)))
            if pair in used_pairs:
                continue
            used_pairs.add(pair)
            take.append(g)
            sims.append(s)
            if len(take) >= per_band:
                break
        out[name] = (take, sims)
    return out


def build_overlap(speakers, pool, rng, turn_s=5.0, rounds=4, overlap=0.0):
    """轮询，但每一轮次提前 overlap*turn_s 开始，形成真实重叠。

    参考 RTTM 带真实重叠区间，评分器计入重叠，所以这是真的重叠测试。
    """
    step = turn_s * (1.0 - overlap)
    order = [i for _ in range(rounds) for i in range(len(speakers))]
    total_s = step * len(order) + turn_s
    canvas = np.zeros(int(total_s * SR) + SR, np.float64)
    segs = []
    for k, i in enumerate(order):
        x = speaker_audio(pool[speakers[i]], turn_s, rng).astype(np.float64)
        b = k * step
        off = int(b * SR)
        canvas[off:off + len(x)] += x
        segs.append((b, b + len(x) / SR, f"SPK{i+1}"))
    peak = np.abs(canvas).max()
    if peak > 32767:
        canvas *= 32767 / peak
    return canvas.astype(np.int16), segs


def write_case(out_dir, name, audio, segs):
    os.makedirs(out_dir, exist_ok=True)
    w = wave.open(f"{out_dir}/{name}.wav", "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(audio.tobytes()); w.close()
    with open(f"{out_dir}/{name}.rttm", "w", encoding="utf-8") as handle:
        for b, e, s in segs:
            handle.write(f"SPEAKER {name} 1 {b:.3f} {e-b:.3f} <NA> <NA> {s} <NA> <NA>\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aishell", required=True)
    ap.add_argument("--campplus", default="asr/harmony/sdk-dingqiao/src/main/resources/"
                                          "rawfile/amphion-dingqiao/campplus.onnx")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()

    pool = load_pool(args.aishell)
    print(f"可用说话人 {len(pool)}")
    emb = speaker_embeddings(pool, args.campplus)
    print(f"声纹 {len(emb)} 条")

    index = []

    # 轴五：说话人音色相似度分层（固定 3 人轮询、5 s 段、无重叠）
    rng = np.random.default_rng(20261103)
    bands = pick_triples(emb, rng, per_band=args.repeats)
    for band, (triples, sims) in bands.items():
        print(f"  音色{band}: 组内最大成对相似度 {min(sims):.3f}~{max(sims):.3f}")
        for rep, (g, s) in enumerate(zip(triples, sims)):
            r = np.random.default_rng(hash((band, rep)) % (2**32))
            audio, segs = build_overlap(list(g), pool, r, turn_s=5.0, rounds=4, overlap=0.0)
            name = f"音色{band}_r{rep}"
            write_case(args.out, name, audio, segs)
            index.append(dict(name=name, group=f"音色{band}", duration=len(audio)/SR,
                              speakers=3, max_pair_sim=s))

    # 轴六：重叠比例（固定 3 人轮询、5 s 段）
    #
    # 说话人组**跨重叠档固定**：音色相似度与混淆率的相关是 r=+0.746，若每档各自抽样，
    # 抽到更易分的一档会被误读成"重叠让结果变好"。这里让重叠成为唯一变量。
    fixed3 = []
    for rep in range(args.repeats):
        r = np.random.default_rng(hash(("ovfix", rep)) % (2**32))
        fixed3.append(list(r.choice(sorted(pool), 3, replace=False)))
    for ov in (0.0, 0.10, 0.25, 0.40):
        for rep in range(args.repeats):
            r = np.random.default_rng(hash(("ov", rep)) % (2**32))
            spk = fixed3[rep]
            audio, segs = build_overlap(spk, pool, r, turn_s=5.0, rounds=4, overlap=ov)
            name = f"重叠{int(ov*100)}pct_r{rep}"
            write_case(args.out, name, audio, segs)
            index.append(dict(name=name, group=f"重叠{int(ov*100)}pct",
                              duration=len(audio)/SR, speakers=3))
        print(f"  重叠{int(ov*100)}% ×{args.repeats}")

    # 轴七：重叠 25% × 人数（看重叠代价是否随人数放大）
    #
    # 同样固定说话人：n 人的无重叠对照直接取自同一组，才能把"重叠的代价"从
    # "这组人好不好分"里剥出来。
    for n in (2, 4):
        for rep in range(args.repeats):
            r0 = np.random.default_rng(hash(("ovnfix", n, rep)) % (2**32))
            spk = list(r0.choice(sorted(pool), n, replace=False))
            for ov, tag in ((0.0, "无重叠"), (0.25, "重叠25pct")):
                r = np.random.default_rng(hash(("ovn", n, rep)) % (2**32))
                audio, segs = build_overlap(spk, pool, r, turn_s=5.0, rounds=4, overlap=ov)
                name = f"{n}人{tag}_r{rep}"
                write_case(args.out, name, audio, segs)
                index.append(dict(name=name, group=f"{n}人{tag}",
                                  duration=len(audio)/SR, speakers=n))
        print(f"  {n}人 无重叠/重叠25% 配对 ×{args.repeats}")

    json.dump(index, open(f"{args.out}/index.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n共 {len(index)} 条，合计 {sum(i['duration'] for i in index)/60:.0f} 分钟")


if __name__ == "__main__":
    main()
