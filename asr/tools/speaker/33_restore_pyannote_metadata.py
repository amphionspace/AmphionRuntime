"""给交付用的 pyannote 分割模型副本补回 sherpa 需要的元数据。

为什么要补：交付件的元数据在改图时被剥掉了（SDK 走自研的 metadata-free powerset
解码，不依赖它），但 sherpa 的 OfflineSpeakerDiarization 在 Init 时强制读 sample_rate
等 8 个字段，缺一个就报 "'sample_rate' does not exist in the metadata"。

参数不是猜的，取自我方 SDK 的 powerset 解码器 `speaker_turn_segmenter.cpp`：
  kWindowSamples=160000  kFrames=589  kClasses=7
  kReceptiveFieldSize=991  kReceptiveFieldShift=270
  powerset 序 empty,S0,S1,S2,S0+S1,S0+S2,S1+S2 → 3 人、最大 2 并发
唯一无从我方代码确定的是 window_shift，所以它可调，并由 32_ 的 --validate
在客户 4 条上对归档数字做经验验证——对不上就说明取值错了。

只写副本，不动交付件本身。
"""
import argparse
import shutil

import onnx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="shared/models/asr/dingqiao/pyannote-segmentation-3.0.onnx")
    ap.add_argument("--dst", required=True)
    ap.add_argument("--window-shift", type=int, default=16000,
                    help="窗移（样本）。默认 16000（窗长的 10%%）；对不上归档数字就换")
    args = ap.parse_args()

    shutil.copyfile(args.src, args.dst)
    model = onnx.load(args.dst)
    meta = {
        "sample_rate": 16000,
        "window_size": 160000,
        "window_shift": args.window_shift,
        "receptive_field_size": 991,
        "receptive_field_shift": 270,
        "num_speakers": 3,
        "powerset_max_classes": 2,
        "num_classes": 7,
    }
    existing = {p.key for p in model.metadata_props}
    for k, v in meta.items():
        if k in existing:
            continue
        entry = model.metadata_props.add()
        entry.key = k
        entry.value = str(v)
    onnx.save(model, args.dst)
    print(f"写出 {args.dst}")
    for k, v in meta.items():
        print(f"  {k} = {v}")


if __name__ == "__main__":
    main()
