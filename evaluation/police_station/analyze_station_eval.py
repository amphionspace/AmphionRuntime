#!/usr/bin/env python3
"""派出所名称批量评测打分。

读取设备端 police_station_eval.tsv（列：timestamp_ms, utt_id, ref_text,
expected_station, asr_raw, normalized, station_extracted, station_valid,
station_hit, sent_match, decode_collapse），汇总：
  - 整名命中率 station_hit（设备端按甲方口径已算好，Y/N）
  - station_valid（抽出的名是否在词表里）
  - sent_match（整句 ref==normalized）
  - decode_collapse（跑飞/复读）计数——回退的重要信号
并列出未命中明细，供人工核查。

用法：python3 analyze_station_eval.py roundX/police_station_eval.tsv
"""
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "round_newmodel/police_station_eval.tsv")
    rows = []
    with path.open(encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in f:
            f_ = line.rstrip("\n").split("\t")
            if len(f_) < len(header):
                f_ += [""] * (len(header) - len(f_))
            rows.append(f_)

    def col(r, name):
        return r[idx[name]] if name in idx and idx[name] < len(r) else ""

    total = len(rows)
    hit = sum(1 for r in rows if col(r, "station_hit") == "Y")
    valid = sum(1 for r in rows if col(r, "station_valid") == "Y")
    sent = sum(1 for r in rows if col(r, "sent_match") == "Y")
    collapse = sum(1 for r in rows if col(r, "decode_collapse") == "Y")

    print(f"文件: {path}")
    print(f"总条数: {total}")
    if total == 0:
        return
    print(f"整名命中 station_hit : {hit}/{total} = {hit/total*100:.2f}%")
    print(f"抽名有效 station_valid: {valid}/{total} = {valid/total*100:.2f}%")
    print(f"整句匹配 sent_match   : {sent}/{total} = {sent/total*100:.2f}%")
    print(f"解码跑飞 decode_collapse: {collapse}/{total} = {collapse/total*100:.2f}%")

    misses = [r for r in rows if col(r, "station_hit") != "Y"]
    print(f"\n未命中明细 ({len(misses)} 条):")
    print("utt_id\texpected_station\tstation_extracted\tcollapse\tasr_raw\tnormalized")
    for r in misses:
        print("\t".join([
            col(r, "utt_id"), col(r, "expected_station"), col(r, "station_extracted"),
            col(r, "decode_collapse"), col(r, "asr_raw"), col(r, "normalized"),
        ]))


if __name__ == "__main__":
    main()
