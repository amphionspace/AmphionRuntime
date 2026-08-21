#!/usr/bin/env python3
"""Compose 200 positive Chinese cases plus 200 negative controls for LAC A/B."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
FIXTURES = SCRIPT_DIR / "fixtures"
OUTPUT = FIXTURES / "hotword_lac_400.jsonl"


def read(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    positive = [entry for entry in read(FIXTURES / "hotword_eval_400.jsonl")
                if entry["language"] == "zh-CN"]
    negative = read(FIXTURES / "hotword_negative_200.jsonl")
    if len(positive) != 200 or len(negative) != 200:
        raise RuntimeError(f"expected 200 positive and 200 negative cases, got {len(positive)}/{len(negative)}")
    entries = positive + negative
    for index, entry in enumerate(entries):
        entry["fixture_index"] = index
    payload = "".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries)
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    OUTPUT.with_suffix(OUTPUT.suffix + ".sha256").write_text(
        f"{digest}  {OUTPUT.name}\n", encoding="ascii")
    print(f"wrote {len(entries)} fixed LAC cases to {OUTPUT}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
