#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
警务 App 菜单/功能名（UI 术语）测试集接入：把 police_ui_20260713（168 条，manifest 含 term 标注）
接入端侧批量评测。

产物（build_ui/ 下，git 忽略）：
  - metadata.jsonl        设备契约 {orig_utt_id, utt_id, text, audio_path}
  - push/metadata.jsonl + push/wavs/*.wav（硬链接）
  - termmap.tsv           utt_id -> term（供 ui_term_hit.py 统计命中）

设备过滤：orig_utt_id = "police_ui_20260713"
"""
import argparse, json, os, sys

ORIG = "police_ui_20260713"


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
    ap.add_argument("--src", required=True, help="police_ui_20260713 数据目录")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_ui"))
    args = ap.parse_args()
    src, out = os.path.abspath(args.src), os.path.abspath(args.out)
    wavs_dir = os.path.join(src, "wavs")
    manifest = os.path.join(src, "manifest.jsonl")
    push_wavs = os.path.join(out, "push", "wavs")
    os.makedirs(push_wavs, exist_ok=True)
    if not os.path.isfile(manifest):
        sys.exit(f"缺 manifest.jsonl: {manifest}")

    meta, termmap, missing = [], [], []
    with open(manifest, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            wav, term, text = o.get("wav", ""), o.get("term", ""), o.get("text", "")
            if not wav or not text:
                continue
            wpath = os.path.join(wavs_dir, wav)
            if not os.path.isfile(wpath):
                missing.append(wav); continue
            utt = os.path.splitext(wav)[0]
            link_or_copy(wpath, os.path.join(push_wavs, wav))
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
    print(f"[build_ui] {len(meta)} 条 -> {out}")
    print(f"  push/ (metadata + wavs/{len(meta)})  termmap.tsv")
    print(f"  distinct terms: {len(set(t for _, t, _ in termmap))}")
    if missing:
        print(f"[warn] 缺 wav {len(missing)}: {missing[:3]}", file=sys.stderr)


if __name__ == "__main__":
    main()
