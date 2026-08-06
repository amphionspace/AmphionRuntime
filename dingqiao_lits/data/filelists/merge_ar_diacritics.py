#!/usr/bin/env python3
"""Merge ar-en filelists into no- / partial- / full-diacritics training rows.

Both inputs use ``wav_path|spk|text``.  For every utterance the output always has a
no-diacritics line.  Additional lines are sampled disjointly:

  - partial: only ambiguous Arabic skeletons keep tashkil (homograph-prioritized)
  - full:    entire vocalized line from --with-diac (random sample, smallest share)

Example:
  python data/filelists/merge_ar_diacritics.py \\
    --no-diac train_no_diac.txt \\
    --with-diac train_with_diac.txt \\
    --output train_mixed.txt \\
    --ratio-partial 0.15 \\
    --ratio-full 0.05 \\
    --seed 42 \\
    --shuffle
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lits.text.arabic_diacritics import (  # noqa: E402
    build_partial_text,
    build_skeleton_form_index,
    classify_arabic_diacritics_level,
    contains_arabic_diacritics,
    sentence_skeleton_ambiguity_score,
    strip_arabic_diacritics,
)


@dataclass
class FilelistRow:
    wav: str
    spk: str
    text: str
    line_no: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge ar-en filelists: all no-diac + optional partial/full rows."
    )
    parser.add_argument("--no-diac", type=Path, required=True, help="Filelist without diacritics.")
    parser.add_argument(
        "--with-diac", type=Path, required=True, help="Filelist with diacritics (same wav paths)."
    )
    parser.add_argument("--output", type=Path, required=True, help="Merged output filelist.")
    parser.add_argument(
        "--ratio-partial",
        type=float,
        default=0.15,
        help="Fraction of utterances that also get a partial-diacritics line (default: 0.15).",
    )
    parser.add_argument(
        "--ratio-full",
        type=float,
        default=0.05,
        help="Fraction of utterances that also get a full-diacritics line (default: 0.05).",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible selection.")
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="Shuffle output lines (recommended before training).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error on alignment / diacritics validation warnings.",
    )
    return parser.parse_args()


def _parse_row(line: str, line_no: int, source: Path) -> FilelistRow:
    parts = line.strip().split("|")
    if len(parts) != 3:
        raise ValueError(f"{source}:{line_no}: expected wav|spk|text, got {len(parts)} fields")
    wav, spk, text = parts
    if not wav or not spk:
        raise ValueError(f"{source}:{line_no}: empty wav or spk")
    return FilelistRow(wav=wav, spk=spk, text=text, line_no=line_no)


def load_filelist(path: Path) -> dict[str, FilelistRow]:
    rows: dict[str, FilelistRow] = {}
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = _parse_row(line, line_no, path)
            if row.wav in rows:
                raise ValueError(f"{path}:{line_no}: duplicate wav path {row.wav!r}")
            rows[row.wav] = row
    if not rows:
        raise ValueError(f"{path}: empty filelist")
    return rows


def _validate_pair(
    wav: str,
    no_row: FilelistRow,
    with_row: FilelistRow,
) -> list[str]:
    warnings: list[str] = []
    if no_row.spk != with_row.spk:
        warnings.append(
            f"{wav}: spk mismatch ({no_row.spk!r} vs {with_row.spk!r}) "
            f"[no-diac line {no_row.line_no}, with-diac line {with_row.line_no}]"
        )
    if contains_arabic_diacritics(no_row.text):
        warnings.append(
            f"{wav}: no-diac filelist contains diacritics (line {no_row.line_no})"
        )
    if not contains_arabic_diacritics(with_row.text):
        warnings.append(
            f"{wav}: with-diac filelist has no diacritics (line {with_row.line_no})"
        )
    stripped = strip_arabic_diacritics(with_row.text)
    if stripped != no_row.text:
        preview_no = no_row.text[:80]
        preview_with = stripped[:80]
        warnings.append(
            f"{wav}: texts differ after stripping diacritics "
            f"(no-diac line {no_row.line_no})\n"
            f"  no-diac : {preview_no!r}\n"
            f"  stripped: {preview_with!r}"
        )
    return warnings


def _count_pick(n_items: int, ratio: float) -> int:
    if ratio <= 0:
        return 0
    if ratio >= 1:
        return n_items
    return int(n_items * ratio)


def _select_homograph_wavs(
    wavs: list[str],
    no_rows: dict[str, FilelistRow],
    *,
    n_pick: int,
    seed: int,
    skeleton_map: dict[str, set[str]],
) -> list[str]:
    if n_pick <= 0:
        return []

    rng = random.Random(seed)
    scored = [
        (
            sentence_skeleton_ambiguity_score(no_rows[wav].text, skeleton_map),
            rng.random(),
            wav,
        )
        for wav in wavs
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = [wav for score, _, wav in scored[:n_pick] if score > 0]
    if len(picked) < n_pick:
        picked.extend(wav for _, _, wav in scored[len(picked) : n_pick])
    return picked[:n_pick]


def merge_filelists(
    no_rows: dict[str, FilelistRow],
    with_rows: dict[str, FilelistRow],
    *,
    ratio_partial: float,
    ratio_full: float,
    seed: int,
    shuffle: bool,
) -> tuple[list[str], dict[str, int | float], list[str]]:
    if not 0.0 <= ratio_partial <= 1.0:
        raise ValueError(f"--ratio-partial must be in [0, 1], got {ratio_partial}")
    if not 0.0 <= ratio_full <= 1.0:
        raise ValueError(f"--ratio-full must be in [0, 1], got {ratio_full}")
    if ratio_partial + ratio_full > 1.0:
        raise ValueError(
            f"ratio_partial + ratio_full must be <= 1, got {ratio_partial + ratio_full}"
        )

    no_keys = set(no_rows)
    with_keys = set(with_rows)
    only_no = sorted(no_keys - with_keys)
    only_with = sorted(with_keys - no_keys)
    if only_no or only_with:
        msg = []
        if only_no:
            msg.append(f"only in --no-diac ({len(only_no)}): {only_no[:3]}")
        if only_with:
            msg.append(f"only in --with-diac ({len(only_with)}): {only_with[:3]}")
        raise ValueError("wav path sets do not match:\n  " + "\n  ".join(msg))

    wavs = sorted(no_keys)
    warnings: list[str] = []
    for wav in wavs:
        warnings.extend(_validate_pair(wav, no_rows[wav], with_rows[wav]))

    skeleton_map = build_skeleton_form_index(row.text for row in with_rows.values())
    ambiguous_skeletons = sum(1 for forms in skeleton_map.values() if len(forms) > 1)

    rng = random.Random(seed)
    n_full = _count_pick(len(wavs), ratio_full)
    full_wavs = set(rng.sample(wavs, n_full)) if n_full else set()

    remaining = [wav for wav in wavs if wav not in full_wavs]
    n_partial = _count_pick(len(wavs), ratio_partial)
    partial_wavs = set(
        _select_homograph_wavs(
            remaining,
            no_rows,
            n_pick=n_partial,
            seed=seed,
            skeleton_map=skeleton_map,
        )
    )

    lines: list[str] = []
    level_counts = {"none": 0, "partial": 0, "full": 0}
    skipped_partial = 0

    for wav in wavs:
        no_row = no_rows[wav]
        with_row = with_rows[wav]
        lines.append(f"{no_row.wav}|{no_row.spk}|{no_row.text}")
        level_counts["none"] += 1

        if wav in partial_wavs:
            partial_text = build_partial_text(no_row.text, with_row.text, skeleton_map)
            if (
                partial_text != no_row.text
                and contains_arabic_diacritics(partial_text)
                and classify_arabic_diacritics_level(partial_text) == "partial"
            ):
                lines.append(f"{no_row.wav}|{no_row.spk}|{partial_text}")
                level_counts["partial"] += 1
            else:
                skipped_partial += 1

        if wav in full_wavs:
            lines.append(f"{with_row.wav}|{with_row.spk}|{with_row.text}")
            level_counts["full"] += 1

    if shuffle:
        rng.shuffle(lines)

    stats = {
        "utterances": len(wavs),
        "output_lines": len(lines),
        "no_diac_lines": level_counts["none"],
        "partial_lines": level_counts["partial"],
        "full_lines": level_counts["full"],
        "partial_candidates": len(partial_wavs),
        "full_candidates": len(full_wavs),
        "skipped_partial": skipped_partial,
        "no_diac_fraction": level_counts["none"] / len(lines) if lines else 1.0,
        "warnings": len(warnings),
        "arabic_skeletons": len(skeleton_map),
        "ambiguous_skeletons": ambiguous_skeletons,
    }
    return lines, stats, warnings


def main() -> int:
    args = parse_args()
    no_rows = load_filelist(args.no_diac.resolve())
    with_rows = load_filelist(args.with_diac.resolve())

    lines, stats, warnings = merge_filelists(
        no_rows,
        with_rows,
        ratio_partial=args.ratio_partial,
        ratio_full=args.ratio_full,
        seed=args.seed,
        shuffle=args.shuffle,
    )

    if warnings:
        print(f"[WARN] {len(warnings)} alignment issue(s):", file=sys.stderr)
        for msg in warnings[:20]:
            print(f"  {msg}", file=sys.stderr)
        if len(warnings) > 20:
            print(f"  ... and {len(warnings) - 20} more", file=sys.stderr)
        if args.strict:
            return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    print(f"no-diac input:    {args.no_diac.resolve()} ({stats['utterances']} utterances)")
    print(f"with-diac input:  {args.with_diac.resolve()}")
    print(
        f"ratios:           partial={args.ratio_partial}, full={args.ratio_full}, "
        f"seed={args.seed}"
    )
    print(f"output:           {args.output.resolve()}")
    print(
        f"lines:            {stats['output_lines']} total "
        f"(none={stats['no_diac_lines']}, partial={stats['partial_lines']}, "
        f"full={stats['full_lines']})"
    )
    print(f"no-diac share:    {stats['no_diac_fraction']:.1%}")
    print(
        f"skeleton index:   {stats['ambiguous_skeletons']} ambiguous / "
        f"{stats['arabic_skeletons']} total Arabic skeletons"
    )
    if stats["skipped_partial"]:
        print(
            f"skipped partial:  {stats['skipped_partial']} candidate(s) had no "
            "ambiguous tokens to vocalize"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
