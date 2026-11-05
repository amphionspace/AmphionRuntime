"""旧模型（community-1：pyannote 分割 + 声纹聚类）在任意音频上的推理。

为什么需要它：此前的场景报告里只有客户 4 条有新旧对比，而那一列用的是交付包里
**预先算好**的 pred-baseline*.rttm，不是我们自己跑的。AliMeeting 28 场、各使用条件
轴、AISHELL-4 全部只有新模型单臂，无法回答"同场景同音频下新旧谁好"。

配置与交付包自带 run_dq5.py 的 baseline 臂逐项一致：
  pyannote 分割 + FastClustering + min_duration_on=0.3 / min_duration_off=0.5
两种聚类口径都支持：
  --clusters N  给定人数（对应归档的 baseline-4spk，24.85%）
  不给          阈值聚类，不给人数（对应归档的 baseline，45.44%，README 称明显误配置）

**使用前必须先过 --validate**：在客户 4 条上复现归档数字，复现不了就说明配置
（尤其声纹模型）与归档不一致，跑出来的旧臂不可比。
"""
import argparse
import glob
import json
import os
import time
import wave

import numpy as np

# 交付件的元数据被剥掉了，sherpa 需要，所以用 33_ 补过元数据的副本（由 --seg 指定）
SEG_DEFAULT = "shared/models/asr/dingqiao/pyannote-segmentation-3.0.onnx"
# community-1 的声纹模型。交付树里 encoder/pool 是拆图的 NPU 改造件，sherpa 要单文件，
# 所以用同一权重的单文件版本。
# eres2net 是经验证的那一个：它在客户 4 条上**精确复现**归档的 24.85% / 45.45%
# （差 0.00pp）。campplus 会给出 15.65% / 42.63%，与归档不符，不可用作旧臂。
EMB_DEFAULT = "shared/models/asr/dingqiao/eres2net.onnx"


def read_wav(path):
    w = wave.open(path, "rb")
    n, ch, sr = w.getnframes(), w.getnchannels(), w.getframerate()
    a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    if ch > 1:
        a = a.reshape(-1, ch)[:, 0]
    return a, sr


def build(seg_model, emb_model, clusters, threshold):
    import sherpa_onnx
    cl = (sherpa_onnx.FastClusteringConfig(num_clusters=clusters) if clusters > 0
          else sherpa_onnx.FastClusteringConfig(threshold=threshold))
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=seg_model),
            num_threads=4),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=emb_model, num_threads=4),
        clustering=cl, min_duration_on=0.3, min_duration_off=0.5)
    return sherpa_onnx.OfflineSpeakerDiarization(cfg)


def predict(diar, audio):
    return sorted((s.start, s.end, f"spk{s.speaker}")
                  for s in diar.process(audio).sort_by_start_time())


def write_rttm(path, name, segs):
    with open(path, "w", encoding="utf-8") as handle:
        for b, e, spk in segs:
            handle.write(f"SPEAKER {name} 1 {b:.3f} {e-b:.3f} <NA> <NA> {spk} <NA> <NA>\n")


def validate(seg_model, emb_model):
    """在客户 4 条上复现归档的 baseline 与 baseline-4spk 数字。"""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "sc", os.path.join(here, "23_score_diarization_scenarios.py"))
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)

    E = os.path.expanduser("~/.cache/amphion-runtime/customer-inputs-20261030/dq5-diar-eval-20261027")
    AUD = os.path.expanduser("~/Downloads/dingqiao-meeting-20260918/audio")
    NAME = {
        "meetingMinutes-20260918-100350-257": "meetingMinutes-20260918-100350-257.wav",
        "meetingMinutes-20260918-102010-230": "meetingMinutes-20260918-102010-230.wav",
        "meetingMinutes-20260918-111223-816": "meetingMinutes-20260918-111223-816.wav",
        "会议-离线-无角色4": "meeting-offline-unknown4.wav",
    }
    from collections import defaultdict
    ref = defaultdict(list)
    for line in open(f"{E}/reference-human-partial.rttm", encoding="utf-8"):
        p = line.split()
        if len(p) > 7 and p[0] == "SPEAKER":
            ref[p[1]].append((float(p[3]), float(p[3]) + float(p[4]), p[7]))

    print(f"分割模型：{seg_model}\n声纹模型：{emb_model}")
    for clusters, label, expect in ((4, "baseline-4spk", 0.2485), (0, "baseline", 0.4545)):
        diar = build(seg_model, emb_model, clusters, 0.5)
        num = den = 0.0
        for rec, fn in NAME.items():
            segs = ref[rec]
            end = max(e for _, e, _ in segs)
            n = int(end / sc.STEP) + 1
            uem = np.zeros(n, bool)
            for b, e, _ in segs:
                uem[max(0, int(b / sc.STEP)):min(n, int(e / sc.STEP))] = True
            audio, _ = read_wav(os.path.join(AUD, fn))
            m = sc.score_one(segs, predict(diar, audio), end, uem)
            num += m["der"] * m["total"]
            den += m["total"]
        got = num / den
        delta = abs(got - expect) * 100
        verdict = "一致" if delta < 1.5 else "**不一致，配置与归档不同，旧臂不可比**"
        print(f"  {label:14s} 本次 {got*100:6.2f}%   归档 {expect*100:6.2f}%   "
              f"差 {delta:4.2f}pp   {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seg", default=SEG_DEFAULT)
    ap.add_argument("--emb", default=EMB_DEFAULT)
    ap.add_argument("--validate", action="store_true", help="在客户 4 条上复现归档数字")
    ap.add_argument("--wav-dir", help="待跑音频目录")
    ap.add_argument("--out", help="RTTM 输出目录")
    ap.add_argument("--clusters", type=int, default=4,
                    help="给定人数；0 表示阈值聚类不给人数")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    if args.validate:
        validate(args.seg, args.emb)
        return
    if not (args.wav_dir and args.out):
        raise SystemExit("需要 --wav-dir 与 --out，或用 --validate")

    os.makedirs(args.out, exist_ok=True)
    diar = build(args.seg, args.emb, args.clusters, args.threshold)
    files = sorted(glob.glob(f"{args.wav_dir}/*.wav"))
    for i, f in enumerate(files, 1):
        name = os.path.basename(f)[:-4]
        dst = f"{args.out}/{name}.rttm"
        if os.path.isfile(dst):
            print(f"[{i}/{len(files)}] 跳过 {name}", flush=True)
            continue
        audio, sr = read_wav(f)
        t0 = time.time()
        segs = predict(diar, audio)
        el = time.time() - t0
        write_rttm(dst, name, segs)
        print(f"[{i}/{len(files)}] {name}  {len(audio)/sr/60:.1f}min  "
              f"推理 {el:.0f}s  RTF {el/(len(audio)/sr):.3f}  "
              f"段 {len(segs)}  人数 {len({s for _,_,s in segs})}", flush=True)
    print("全部完成")


if __name__ == "__main__":
    main()
