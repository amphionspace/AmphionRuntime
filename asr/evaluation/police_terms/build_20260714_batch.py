#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
甲方 20260714 批 UI 术语测试集接入（交付文件名 asr_ui_terms_teacher，manifest 含 target_word）。
manifest 每行：{utt_id, text, target_word, wav, asr, cer, ...}（asr/cer 为对方参考引擎结果，忽略）。
wav 文件名带说话人后缀（ui_tNN_sM_sK.wav），故设备 utt_id 用 wav basename 保唯一。

产物（build_20260714_batch/，git 忽略）：metadata.jsonl + push/wavs（硬链接）+ termmap.tsv
设备过滤：orig_utt_id = "police_ui_20260714"
"""
import argparse, json, os, sys

ORIG = "police_ui_20260714"


def link_or_copy(src, dst):
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        import shutil
        shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="asr_ui_terms_teacher 数据目录")
    ap.add_argument("--manifest", default="manifest_asr_test_teacher.jsonl")
    ap.add_argument("--wavs", default="wavs_teacher")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_20260714_batch"))
    args = ap.parse_args()
    src, out = os.path.abspath(args.src), os.path.abspath(args.out)
    wavs_dir = os.path.join(src, args.wavs)
    manifest = os.path.join(src, args.manifest)
    push_wavs = os.path.join(out, "push", "wavs")
    os.makedirs(push_wavs, exist_ok=True)
    if not os.path.isfile(manifest):
        sys.exit(f"缺 manifest: {manifest}")

    meta, termmap, missing = [], [], []
    with open(manifest, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            wav = os.path.basename(o.get("wav", ""))
            term = o.get("target_word", "") or o.get("term", "")
            text = o.get("text", "")
            if not wav or not text:
                continue
            wp = os.path.join(wavs_dir, wav)
            if not os.path.isfile(wp):
                missing.append(wav); continue
            utt = os.path.splitext(wav)[0]
            link_or_copy(wp, os.path.join(push_wavs, wav))
            meta.append(json.dumps({"orig_utt_id": ORIG, "utt_id": utt,
                                    "text": text, "audio_path": f"wavs/{wav}"}, ensure_ascii=False))
            termmap.append((utt, term, text))

    if not meta:
        sys.exit("未生成用例")
    for p in (os.path.join(out, "metadata.jsonl"), os.path.join(out, "push", "metadata.jsonl")):
        open(p, "w", encoding="utf-8").write("\n".join(meta) + "\n")
    with open(os.path.join(out, "termmap.tsv"), "w", encoding="utf-8") as f:
        f.write("utt_id\tterm\ttext\n")
        for u, t, x in termmap:
            f.write(f"{u}\t{t}\t{x}\n")
    print(f"[build_20260714_batch] {len(meta)} 条, {len(set(t for _, t, _ in termmap))} 词 -> {out}")
    if missing:
        print(f"[warn] 缺 wav {len(missing)}: {missing[:3]}", file=sys.stderr)


if __name__ == "__main__":
    main()
