#!/usr/bin/env python3
"""Remove filelist entries whose start/end segment bounds exceed wav duration."""

from __future__ import annotations

import argparse
from pathlib import Path

import soundfile as sf

DEFAULT_INPUT = Path(
    "/chenmingjie/xingwen/multiling_up-to-date/data/filelists/before_mix/en_short_LJfemale_arpa.txt"
)
DEFAULT_WAV_ROOT = Path("/chenmingjie/xingwen/dataset/en_short_LJfemale_16k")
DEFAULT_OLD_PREFIX = "/mnt/nas/hanxingwen/short_samples_synthesis/output/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Drop invalid segmented filelist entries.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None, help="Defaults to overwrite --input")
    parser.add_argument(
        "--wav-root",
        type=Path,
        default=DEFAULT_WAV_ROOT,
        help="Directory containing wav files referenced by basename",
    )
    parser.add_argument(
        "--old-prefix",
        type=str,
        default=DEFAULT_OLD_PREFIX,
        help="Replace this wav path prefix with --wav-root/<basename>",
    )
    parser.add_argument(
        "--new-prefix",
        type=str,
        default=None,
        help="Optional explicit wav path prefix; defaults to --wav-root",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path to write removed lines",
    )
    return parser.parse_args()


def resolve_wav_path(wav_path: str, wav_root: Path, old_prefix: str, new_prefix: Path | None) -> Path:
    if new_prefix is not None:
        return Path(str(new_prefix).rstrip("/")) / Path(wav_path).name
    if old_prefix and wav_path.startswith(old_prefix):
        return wav_root / Path(wav_path).name
    path = Path(wav_path)
    if path.is_file():
        return path
    fallback = wav_root / path.name
    return fallback


def get_duration(path: Path, cache: dict[Path, float]) -> float | None:
    if path not in cache:
        if not path.is_file():
            cache[path] = None
        else:
            cache[path] = float(sf.info(path).duration)
    return cache[path]


def is_valid_segment(start: float, end: float, duration: float, eps: float = 1e-3) -> bool:
    if start < 0 or end <= start:
        return False
    if start >= duration - eps:
        return False
    if end > duration + eps:
        return False
    return True


def main() -> None:
    args = parse_args()
    output_path = args.output or args.input
    new_prefix = Path(args.new_prefix) if args.new_prefix else args.wav_root

    kept: list[str] = []
    removed: list[str] = []
    duration_cache: dict[Path, float | None] = {}

    with args.input.open("r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    for line_no, line in enumerate(lines, start=1):
        parts = line.split("|")
        if len(parts) != 5:
            removed.append(f"L{line_no}\tbad_format\t{line}")
            continue

        wav_path, spk, start_raw, end_raw, text = parts
        try:
            start = float(start_raw)
            end = float(end_raw)
        except ValueError:
            removed.append(f"L{line_no}\tbad_time\t{line}")
            continue

        resolved = resolve_wav_path(wav_path, args.wav_root, args.old_prefix, new_prefix)
        duration = get_duration(resolved, duration_cache)
        if duration is None:
            removed.append(f"L{line_no}\tmissing_wav\t{resolved}\t{line}")
            continue

        if not is_valid_segment(start, end, duration):
            removed.append(
                f"L{line_no}\tout_of_range\t{resolved.name}\t"
                f"start={start:.6f}\tend={end:.6f}\tdur={duration:.6f}\t{text}"
            )
            continue

        new_wav = str(new_prefix / resolved.name)
        kept.append(f"{new_wav}|{spk}|{start_raw}|{end_raw}|{text}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(kept) + ("\n" if kept else ""))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8") as f:
            f.write("\n".join(removed) + ("\n" if removed else ""))

    print(f"Input lines : {len(lines)}")
    print(f"Kept lines  : {len(kept)}")
    print(f"Removed     : {len(removed)}")
    print(f"Output      : {output_path}")
    if args.report:
        print(f"Report      : {args.report}")


if __name__ == "__main__":
    main()
