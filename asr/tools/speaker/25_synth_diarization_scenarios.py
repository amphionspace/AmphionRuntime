"""用 AISHELL-3 合成受控的角色分离场景，逐帧真值，输出音频 + 参考 RTTM。

为什么要合成：AISHELL-4 全是 5~7 人，**全部超出 maxSpeakers=4**，所以产品标称场景
（2/3/4 人）除了客户那 4 条之外没有任何场景数据。合成集填这个缺口，并提供单轴扫描。

噪声源刻意用**丁桥录音里的真实房间静音段**，不用白噪声、不用人造混响：噪声来自目标
环境本身。

限制（必须随结果一起说）：AISHELL-3 是录音棚朗读语音，拼接出的轮替边界过于干净、
没有真实房间物理。合成集只能刻画**算法沿各轴的行为**，绝对数字不可外推到远场。
"""
import argparse
import glob
import json
import os
import wave
from collections import defaultdict

import numpy as np

SR = 16000


def load_pool(aishell_dir, min_clips=6):
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
    """把该说话人的若干短句拼到指定时长；不足则循环复用。"""
    need = int(seconds * SR)
    out = []
    total = 0
    order = list(files)
    rng.shuffle(order)
    i = 0
    while total < need:
        x = read_wav(order[i % len(order)])
        out.append(x)
        total += len(x)
        i += 1
        if i > len(order) * 4:
            break
    return np.concatenate(out)[:need]


def collect_noise(dingqiao_dir, turns_json, max_seconds=600):
    """从丁桥录音的无人发言处收集真实房间噪声。"""
    if not os.path.isfile(turns_json):
        return None
    turns = json.load(open(turns_json))
    names = {
        "meetingMinutes-20260918-100350-257": "meetingMinutes-20260918-100350-257.wav",
        "meetingMinutes-20260918-102010-230": "meetingMinutes-20260918-102010-230.wav",
        "meetingMinutes-20260918-111223-816": "meetingMinutes-20260918-111223-816.wav",
        "会议-离线-无角色4": "meeting-offline-unknown4.wav",
    }
    chunks = []
    total = 0
    for rec, fn in names.items():
        path = os.path.join(dingqiao_dir, fn)
        if not os.path.isfile(path) or rec not in turns:
            continue
        x = read_wav(path)
        speech = np.zeros(len(x), bool)
        for t in turns[rec]:
            speech[int(t["begin"] * SR):int(t["end"] * SR)] = True
        runs = []
        i = 0
        while i < len(speech):
            if speech[i]:
                i += 1
                continue
            j = i
            while j < len(speech) and not speech[j]:
                j += 1
            if j - i >= SR:
                runs.append((i, j))
            i = j
        for a, b in runs:
            chunks.append(x[a:b])
            total += b - a
            if total >= max_seconds * SR:
                break
        if total >= max_seconds * SR:
            break
    return np.concatenate(chunks) if chunks else None


def mix_noise(clean, noise, snr_db, rng):
    if noise is None or len(noise) == 0:
        return clean
    need = len(clean)
    reps = int(np.ceil(need / len(noise)))
    tiled = np.tile(noise, reps)[:need].astype(np.float64)
    c = clean.astype(np.float64)
    pc = np.mean(c ** 2)
    pn = np.mean(tiled ** 2)
    if pn <= 0 or pc <= 0:
        return clean
    scale = np.sqrt(pc / (pn * (10 ** (snr_db / 10.0))))
    out = c + tiled * scale
    peak = np.abs(out).max()
    if peak > 32767:
        out = out * (32767 / peak)
    return out.astype(np.int16)


def build(scenario, pool, rng, noise=None):
    """按场景描述拼出音频与参考段。返回 (int16 音频, [(begin,end,speaker)])。"""
    speakers = rng.choice(sorted(pool), scenario["speakers"], replace=False)
    turn_s = scenario["turn_seconds"]
    gap_s = scenario.get("gap_seconds", 0.3)
    rounds = scenario["rounds"]
    pattern = scenario.get("pattern", "roundrobin")

    order = []
    for r in range(rounds):
        idx = list(range(len(speakers)))
        if pattern == "sequential":
            # 严格依次：每人把自己全部轮次一次说完
            continue
        if pattern == "random":
            rng.shuffle(idx)
        order += idx
    if pattern == "sequential":
        order = [i for i in range(len(speakers)) for _ in range(rounds)]

    audio = []
    segs = []
    cursor = 0.0
    for i in order:
        x = speaker_audio(pool[speakers[i]], turn_s, rng)
        audio.append(x)
        segs.append((cursor, cursor + len(x) / SR, f"SPK{i+1}"))
        cursor += len(x) / SR
        gap = int(gap_s * SR)
        if gap > 0:
            audio.append(np.zeros(gap, np.int16))
            cursor += gap_s
    out = np.concatenate(audio)
    if scenario.get("snr_db") is not None:
        out = mix_noise(out, noise, scenario["snr_db"], rng)
    return out, segs


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
    ap.add_argument("--aishell", required=True, help="16 kHz AISHELL-3 wav 目录")
    ap.add_argument("--dingqiao", default=os.path.expanduser(
        "~/Downloads/dingqiao-meeting-20260918/audio"))
    ap.add_argument("--turns", default="", help="sf_turns_perslot.json，用于取真实房间噪声")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=5, help="每个场景的独立样本数")
    args = ap.parse_args()

    pool = load_pool(args.aishell)
    print(f"可用说话人 {len(pool)}")
    noise = collect_noise(args.dingqiao, args.turns) if args.turns else None
    if noise is not None:
        print(f"真实房间噪声 {len(noise)/SR:.0f}s")

    cases = []
    # 轴一：标称容量内的人数 × 轮替方式（最大缺口）
    for n in (2, 3, 4):
        for pattern in ("sequential", "roundrobin"):
            cases.append(dict(group=f"{n}人-{pattern}", speakers=n, turn_seconds=5.0,
                              rounds=4, pattern=pattern))
    # 轴二：单人误拆（同一人连说）
    cases.append(dict(group="单人-5分钟", speakers=1, turn_seconds=30.0, rounds=10,
                      pattern="roundrobin", gap_seconds=0.5))
    # 轴三：发言时长（固定 3 人轮询）
    for t in (1.0, 2.0, 3.0, 5.0, 10.0):
        cases.append(dict(group=f"段长{t:g}s", speakers=3, turn_seconds=t,
                          rounds=max(3, int(40 / t)), pattern="roundrobin"))
    # 轴四：真实房间噪声 SNR（固定 3 人轮询）
    if noise is not None:
        for snr in (20, 15, 10, 5):
            cases.append(dict(group=f"SNR{snr}dB", speakers=3, turn_seconds=5.0,
                              rounds=4, pattern="roundrobin", snr_db=snr))

    index = []
    for case in cases:
        for rep in range(args.repeats):
            rng = np.random.default_rng(hash((case["group"], rep)) % (2**32))
            audio, segs = build(case, pool, rng, noise)
            name = f"{case['group']}_r{rep}".replace("/", "-")
            write_case(args.out, name, audio, segs)
            index.append(dict(name=name, group=case["group"],
                              duration=len(audio) / SR, speakers=case["speakers"]))
        print(f"  {case['group']:18s} ×{args.repeats}  "
              f"{index[-1]['duration']:.0f}s/条")
    json.dump(index, open(f"{args.out}/index.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n共 {len(index)} 条，合计 {sum(i['duration'] for i in index)/60:.0f} 分钟")


if __name__ == "__main__":
    main()
