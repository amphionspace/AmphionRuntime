#!/usr/bin/env python3
"""车牌号批量评测打分（冀R / 辽B 拆分）。

读取设备端 plate_eval.tsv（列：timestamp_ms, expected_plate, asr_raw,
normalized, plate_extracted, plate_valid）。整牌命中定义：
  规整后 expected_plate == plate_extracted（去空格/·/- 、字母大写）。
按车牌省份前缀（冀R / 辽B / 其他）分组统计命中率，并列未命中明细。

用法：python3 analyze_plate_eval.py roundX/plate_eval.tsv
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

_STRIP = re.compile(r"[\s·、\-—_]")


def norm_plate(s: str) -> str:
    return _STRIP.sub("", s).upper()


def province(expected: str) -> str:
    p = norm_plate(expected)
    if p.startswith("冀R"):
        return "冀R"
    if p.startswith("辽B"):
        return "辽B"
    return "其他"


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "round_newmodel/plate_eval.tsv")
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
    print(f"文件: {path}")
    print(f"总条数: {total}")
    if total == 0:
        return

    # [hit, total, valid]
    grp = defaultdict(lambda: [0, 0, 0])
    misses = []
    for r in rows:
        exp = col(r, "expected_plate")
        ext = col(r, "plate_extracted")
        valid = col(r, "plate_valid") == "Y"
        prov = province(exp)
        hit = norm_plate(exp) != "" and norm_plate(exp) == norm_plate(ext)
        for key in (prov, "合计"):
            grp[key][1] += 1
            if hit:
                grp[key][0] += 1
            if valid:
                grp[key][2] += 1
        if not hit:
            misses.append((prov, exp, ext, valid, col(r, "asr_raw"), col(r, "normalized")))

    print("\n整牌命中率（规整后 expected==extracted）:")
    print(f"{'分组':<6}{'命中':>8}{'总数':>8}{'命中率':>10}{'有效率':>10}")
    for key in ("冀R", "辽B", "其他", "合计"):
        if grp[key][1] == 0:
            continue
        h, t, v = grp[key]
        print(f"{key:<6}{h:>8}{t:>8}{h/t*100:>9.2f}%{v/t*100:>9.2f}%")

    print(f"\n未命中明细 ({len(misses)} 条):")
    print("分组\texpected_plate\tplate_extracted\tvalid\tasr_raw\tnormalized")
    for m in misses:
        prov, exp, ext, valid, raw, norm = m
        print(f"{prov}\t{exp}\t{ext}\t{'Y' if valid else 'N'}\t{raw}\t{norm}")


if __name__ == "__main__":
    main()
