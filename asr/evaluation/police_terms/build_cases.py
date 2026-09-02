#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 0 工装：把 police_terms_20260711 的 4 类合成数据接入端侧批量评测。

输入：--src 指向 test_data/police_terms_20260711（含 4 个类别子目录，
      每个含 transcript.jsonl + wavs/）。transcript.jsonl 的 `text` 为标准答案，
      `utt_id` 已全局唯一且带类别前缀（vocab_/appname_/specialcode_/policedialog_）。

产物（默认写到本脚本同级 build/ 下，git 忽略）：
  - cases.tsv             utt_id / text / category / wav_abspath （人读+复核用）
  - build/metadata.jsonl  设备端 BatchEvalManifest 契约：{orig_utt_id, utt_id, text, audio_path}
  - build/push/wavs/*.wav 全部 wav 的硬链接（同卷零拷贝），供 push_batch_eval.sh 一次推送
  - build/push/metadata.jsonl 同上（放进 push 根，adb push 一把梭）

设备过滤：orig_utt_id = "police_terms_20260711_<catkey>"（startsWith 前缀过滤）
  - 跑全部：   --es filter police_terms_20260711
  - 只跑某类： --es filter police_terms_20260711_appname
"""
import argparse
import json
import os
import sys

# 类别子目录名 -> (catkey, wav 前缀)。catkey 用于 orig_utt_id 与分类别统计。
CATEGORIES = {
    "警务术语_行业词汇": ("vocab", "vocab_"),
    "警务术语_行业对话": ("dialog", "policedialog_"),
    "警务术语_应用名称": ("appname", "appname_"),
    "警务术语_特殊代码": ("specialcode", "specialcode_"),
}

ORIG_PREFIX = "police_terms_20260711"


def link_or_copy(src, dst):
    """同卷优先硬链接（零拷贝）；跨卷回退复制。"""
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        import shutil
        shutil.copy2(src, dst)


def main():
    ap = argparse.ArgumentParser(description="build police_terms batch-eval cases")
    ap.add_argument(
        "--src",
        required=True,
        help="police_terms_20260711 根目录",
    )
    ap.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "build"),
        help="产物输出目录（默认 asr/evaluation/police_terms/build）",
    )
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    out = os.path.abspath(args.out)
    push_dir = os.path.join(out, "push")
    push_wavs = os.path.join(push_dir, "wavs")
    os.makedirs(push_wavs, exist_ok=True)

    if not os.path.isdir(src):
        sys.exit(f"[build] 找不到 --src 目录: {src}")

    cases_rows = []          # (utt_id, text, catkey, wav_abspath)
    metadata_lines = []      # jsonl str
    per_cat = {}
    missing_wav = []

    for subdir, (catkey, prefix) in CATEGORIES.items():
        cat_root = os.path.join(src, subdir)
        transcript = os.path.join(cat_root, "transcript.jsonl")
        wavs_dir = os.path.join(cat_root, "wavs")
        if not os.path.isfile(transcript):
            print(f"[build][warn] 缺 transcript.jsonl: {transcript}", file=sys.stderr)
            continue
        n = 0
        with open(transcript, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                utt_id = obj.get("utt_id", "").strip()
                text = obj.get("text", "").strip()
                if not utt_id or not text:
                    continue
                wav_name = f"{utt_id}.wav"
                wav_abspath = os.path.join(wavs_dir, wav_name)
                if not os.path.isfile(wav_abspath):
                    missing_wav.append(wav_abspath)
                    continue
                # 设备端 flat wavs/：utt_id 全局唯一，直接平铺
                link_or_copy(wav_abspath, os.path.join(push_wavs, wav_name))
                cases_rows.append((utt_id, text, catkey, wav_abspath))
                metadata_lines.append(json.dumps({
                    "orig_utt_id": f"{ORIG_PREFIX}_{catkey}",
                    "utt_id": utt_id,
                    "text": text,
                    "audio_path": f"wavs/{wav_name}",
                }, ensure_ascii=False))
                n += 1
        per_cat[catkey] = n

    if not cases_rows:
        sys.exit("[build] 未生成任何用例，检查 --src 结构")

    # cases.tsv（人读复核）
    cases_tsv = os.path.join(out, "cases.tsv")
    with open(cases_tsv, "w", encoding="utf-8") as f:
        f.write("utt_id\ttext\tcategory\twav\n")
        for utt_id, text, catkey, wav in cases_rows:
            safe_text = text.replace("\t", " ").replace("\n", " ")
            f.write(f"{utt_id}\t{safe_text}\t{catkey}\t{wav}\n")

    # metadata.jsonl（设备契约）——同时写到 out 根与 push 根
    for path in (os.path.join(out, "metadata.jsonl"),
                 os.path.join(push_dir, "metadata.jsonl")):
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(metadata_lines) + "\n")

    total = len(cases_rows)
    print(f"[build] src = {src}")
    print(f"[build] out = {out}")
    print(f"[build] cases.tsv         -> {cases_tsv}")
    print(f"[build] metadata.jsonl    -> {os.path.join(out, 'metadata.jsonl')}")
    print(f"[build] push/ (adb 源)    -> {push_dir}  (metadata.jsonl + wavs/{total})")
    print("[build] 分类别条数:")
    for catkey in ("dialog", "vocab", "appname", "specialcode"):
        if catkey in per_cat:
            print(f"          {catkey:12s} {per_cat[catkey]}")
    print(f"[build] 合计 {total} 条")
    if missing_wav:
        print(f"[build][warn] 缺失 wav {len(missing_wav)} 条（已跳过），前 3 条:", file=sys.stderr)
        for w in missing_wav[:3]:
            print(f"          {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
