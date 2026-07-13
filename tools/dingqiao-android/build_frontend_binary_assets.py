#!/usr/bin/env python3
"""Build the compact frontend dictionaries consumed by Android and HarmonyOS.

The binary format is intentionally small and stable because it is parsed by the
SDKs without a third-party runtime:

* chinese_lexicon.bin: ``LPY1`` + count + (UTF-8 word, UTF-8 pinyin)*
* cmudict.bin: ``CMD1`` + count + (UTF-8 word, phone-count, UTF-8 phone*)*

The runtime applies ``chinese_surname_lexicon.txt`` after loading the Chinese
binary, so that override file remains a separate text input.

All integers are signed 32-bit big-endian values, matching the Android reader.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


DEFAULT_MODEL_ID = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
DEFAULT_VERSION = "0.1.0"
WORD_PINYIN_MAGIC = 0x4C505931  # LPY1
CMUDICT_MAGIC = 0x434D4431  # CMD1


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=repo_root / "tts" / "tools" / "trial-export" / DEFAULT_MODEL_ID / DEFAULT_VERSION,
        help="Model package containing the source .txt dictionaries.",
    )
    return parser.parse_args()


def read_word_pinyin(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        parts = trimmed.split("\t")
        if len(parts) == 2:
            entries[parts[0]] = parts[1]
    return entries


def read_cmudict(path: Path) -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        parts = trimmed.split("\t", 1)
        if len(parts) != 2:
            continue
        key = parts[0].split("(", 1)[0].upper()
        if key in entries:
            continue
        phones = parts[1].strip().split()
        if phones:
            entries[key] = phones
    return entries


def write_utf8(output: bytearray, value: str) -> None:
    encoded = value.encode("utf-8")
    output.extend(struct.pack(">i", len(encoded)))
    output.extend(encoded)


def build_word_pinyin(entries: dict[str, str]) -> bytes:
    output = bytearray(struct.pack(">ii", WORD_PINYIN_MAGIC, len(entries)))
    for word, pinyin in entries.items():
        write_utf8(output, word)
        write_utf8(output, pinyin)
    return bytes(output)


def build_cmudict(entries: dict[str, list[str]]) -> bytes:
    output = bytearray(struct.pack(">ii", CMUDICT_MAGIC, len(entries)))
    for word, phones in entries.items():
        write_utf8(output, word)
        output.extend(struct.pack(">i", len(phones)))
        for phone in phones:
            write_utf8(output, phone)
    return bytes(output)


def write_if_changed(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == content:
        return
    path.write_bytes(content)


def update_manifest_sizes(model_dir: Path) -> None:
    manifest_path = model_dir / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sizes = {
        "chinese_lexicon.bin": (model_dir / "chinese_lexicon.bin").stat().st_size,
        "cmudict.bin": (model_dir / "cmudict.bin").stat().st_size,
    }
    changed = False
    for entry in manifest.get("files", []):
        name = entry.get("name")
        if name in sizes and entry.get("size_bytes") != sizes[name]:
            entry["size_bytes"] = sizes[name]
            changed = True
    if changed:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir.resolve()
    chinese_text = model_dir / "chinese_lexicon.txt"
    cmudict_text = model_dir / "cmudict.txt"
    for source in (chinese_text, cmudict_text):
        if not source.is_file():
            raise FileNotFoundError(f"missing frontend dictionary: {source}")

    word_pinyin = read_word_pinyin(chinese_text)
    cmudict = read_cmudict(cmudict_text)
    write_if_changed(model_dir / "chinese_lexicon.bin", build_word_pinyin(word_pinyin))
    write_if_changed(model_dir / "cmudict.bin", build_cmudict(cmudict))
    update_manifest_sizes(model_dir)
    print(f"built chinese_lexicon.bin entries={len(word_pinyin)}")
    print(f"built cmudict.bin entries={len(cmudict)}")


if __name__ == "__main__":
    main()
