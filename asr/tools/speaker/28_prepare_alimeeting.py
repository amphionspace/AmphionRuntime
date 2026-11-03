"""把 AliMeeting Eval 准备成评分可用的形式：TextGrid → RTTM，音频 → 16 kHz 单声道。

为什么要这份数据：标称容量（2~4 人）内此前只有客户 4 条真实录音，样本太少。
AliMeeting Eval 是 8 场真实中文远场会议，2~4 人，带人工标注，正好补这个缺口。

近场/远场配对是额外收获：同一场会议既有 8 通道阵列（远场），又有每人一路耳麦
（近场）。把耳麦路按时间轴相加合成一轨，就得到"同内容、同说话人、无房间"的对照，
能把**真实混响与距离的代价**单独量出来——这是合成集给不了的。

远场取 ch0，与 AISHELL-4 的处理一致，保持可比。
"""
import argparse
import glob
import os
import re
import subprocess
import sys

SR = 16000


def parse_textgrid(path):
    """返回 {说话人: [(begin, end)]}。AliMeeting 每个 IntervalTier 是一个说话人，
    tier 名即说话人 ID；text 非空的区间才算发言。"""
    text = open(path, encoding="utf-8").read()
    out = {}
    # 按 item [n]: 切块，每块一个 tier
    blocks = re.split(r"\n\s*item\s*\[\d+\]:", text)[1:]
    for block in blocks:
        m = re.search(r'name\s*=\s*"([^"]*)"', block)
        if not m:
            continue
        spk = m.group(1)
        segs = []
        for iv in re.finditer(
                r"xmin\s*=\s*([\d.]+)\s*\n\s*xmax\s*=\s*([\d.]+)\s*\n\s*text\s*=\s*\"([^\"]*)\"",
                block):
            begin, end, label = float(iv.group(1)), float(iv.group(2)), iv.group(3).strip()
            if label and end > begin:
                segs.append((begin, end))
        if segs:
            out[spk] = segs
    return out


def write_rttm(path, name, per_speaker):
    with open(path, "w", encoding="utf-8") as handle:
        for spk, segs in sorted(per_speaker.items()):
            for begin, end in segs:
                handle.write(f"SPEAKER {name} 1 {begin:.3f} {end-begin:.3f} "
                             f"<NA> <NA> {spk} <NA> <NA>\n")


def ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:400])


def far_ch0(src, dst):
    """取 8 通道阵列的第 0 路，重采样到 16 kHz 单声道 16-bit。"""
    # pan 而非已移除的 -map_channel；c0=c0 精确取第 0 路，不做通道平均
    ffmpeg(["-i", src, "-filter_complex", "pan=mono|c0=c0",
            "-ar", str(SR), "-acodec", "pcm_s16le", dst])


def near_mix(srcs, dst):
    """把每人一路耳麦按时间轴相加成一轨。

    用 amix 而不是简单平均：amix 会按输入数归一，避免削波；各路同长同起点
    （同一场会议的统一时间轴），所以相加即可还原"无房间的同一场会议"。
    """
    args = []
    for s in srcs:
        args += ["-i", s]
    args += ["-filter_complex",
             f"amix=inputs={len(srcs)}:duration=longest:dropout_transition=0,"
             f"aresample={SR}",
             "-ac", "1", "-acodec", "pcm_s16le", dst]
    ffmpeg(args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="解包后的 Eval_Ali 目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms", default="far,near")
    args = ap.parse_args()

    arms = args.arms.split(",")
    for arm in arms:
        os.makedirs(f"{args.out}/{arm}", exist_ok=True)

    tg_dir = f"{args.root}/Eval_Ali_far/textgrid_dir"
    sessions = sorted(os.path.basename(p)[:-9]
                      for p in glob.glob(f"{tg_dir}/*.TextGrid"))
    print(f"场次 {len(sessions)}")

    rows = []
    for name in sessions:
        per = parse_textgrid(f"{tg_dir}/{name}.TextGrid")
        total = sum(e - b for segs in per.values() for b, e in segs)
        end = max(e for segs in per.values() for _, e in segs)
        rows.append((name, len(per), end / 60, total / 60))

        far_src = glob.glob(f"{args.root}/Eval_Ali_far/audio_dir/{name}_*.wav")
        near_srcs = sorted(glob.glob(
            f"{args.root}/Eval_Ali_near/audio_dir/{name}_N_*.wav"))

        for arm in arms:
            write_rttm(f"{args.out}/{arm}/{name}.rttm", name, per)
            dst = f"{args.out}/{arm}/{name}.wav"
            if os.path.isfile(dst):
                continue
            if arm == "far":
                if not far_src:
                    print(f"  [跳过] {name} 无远场音频", file=sys.stderr)
                    continue
                far_ch0(far_src[0], dst)
            else:
                if not near_srcs:
                    print(f"  [跳过] {name} 无近场音频", file=sys.stderr)
                    continue
                near_mix(near_srcs, dst)
        print(f"  {name:18s} {len(per)} 人  {end/60:5.1f} min  "
              f"发言 {total/60:5.1f} min  近场 {len(near_srcs)} 路")

    print(f"\n人数分布: " + ", ".join(
        f"{n} 人×{sum(1 for r in rows if r[1]==n)}"
        for n in sorted({r[1] for r in rows})))
    print(f"合计 {sum(r[2] for r in rows):.0f} 分钟音频，"
          f"{sum(r[3] for r in rows):.0f} 分钟发言")


if __name__ == "__main__":
    main()
