#!/usr/bin/env python3
"""Load and validate the shared Dingqiao Android/HarmonyOS parameter contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "shared/api-spec/dingqiao-asr-parameters.json"


class ParameterContractError(ValueError):
    pass


def load_contract(payload: bytes | None = None) -> dict[str, Any]:
    raw = CONTRACT_PATH.read_bytes() if payload is None else payload
    try:
        contract = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ParameterContractError(f"invalid parameter contract JSON: {error}") from error
    if contract.get("schema_version") != 1:
        raise ParameterContractError("unsupported parameter contract schema_version")
    if contract.get("contract_id") != "dingqiao-asr-cross-platform-parameters":
        raise ParameterContractError("unexpected parameter contract id")
    return contract


def _table_rows(markdown: str, key: str) -> list[list[str]]:
    pattern = re.compile(rf"^\s*\|\s*`{re.escape(key)}`\s*\|", re.MULTILINE)
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        if not pattern.match(line):
            continue
        rows.append([column.strip() for column in line.strip().strip("|").split("|")])
    return rows


def _default_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, "g")
    return str(value)


def validate_parameter_document(
    markdown: str,
    contract: dict[str, Any] | None = None,
) -> None:
    spec = load_contract() if contract is None else contract
    required_keys = {
        *spec["common_delivery_profile"]["audio"].keys(),
        *spec["create_engine"]["fields"].keys(),
        *spec["create_engine"]["extra_params"].keys(),
        *spec["start"]["fields"].keys(),
        *spec["start"]["extra_params"].keys(),
        *spec["speaker_diarization"]["fields"].keys(),
        *spec["voiceprint_register"]["fields"].keys(),
    }
    # frameBytes is a writeAudio constant rather than a public object field.
    required_keys.remove("frameBytes")
    missing = sorted(key for key in required_keys if not _table_rows(markdown, key))
    if missing:
        raise ParameterContractError(
            f"parameter document missing common key: {missing[0]}"
        )

    static_defaults: dict[str, object] = {
        **spec["common_delivery_profile"]["audio"],
        **{
            key: value["default"]
            for key, value in spec["create_engine"]["fields"].items()
            if "default" in value
        },
        **{
            key: value["default"]
            for key, value in spec["create_engine"]["extra_params"].items()
            if "default" in value and value["default"] not in (None, [])
        },
        **{
            key: value["default"]
            for key, value in spec["start"]["extra_params"].items()
            if "default" in value and value["default"] not in (None, [])
        },
        **{
            key: value["default"]
            for key, value in spec["speaker_diarization"]["fields"].items()
            if "default" in value
        },
    }
    static_defaults.pop("frameBytes", None)
    for key, expected in sorted(static_defaults.items()):
        rows = _table_rows(markdown, key)
        expected_text = _default_text(expected)
        if not any(len(row) >= 3 and expected_text in row[2] for row in rows):
            raise ParameterContractError(
                f"parameter document default mismatch: {key} expected {expected_text}"
            )

    frame_bytes = spec["common_delivery_profile"]["audio"]["frameBytes"]
    if str(frame_bytes) not in markdown or "writeAudio" not in markdown:
        raise ParameterContractError(
            f"parameter document missing writeAudio frameBytes={frame_bytes}"
        )

    enhancement = spec["platform_extensions"]["harmony"][
        "enableTargetSpeakerEnhancement"
    ]
    if enhancement.get("common_customer_configuration") is not False:
        raise ParameterContractError(
            "Harmony target-speaker enhancement must remain outside common configuration"
        )


def canonical_contract_bytes() -> bytes:
    return CONTRACT_PATH.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path, nargs="+")
    args = parser.parse_args()
    contract = load_contract()
    for path in args.markdown:
        try:
            validate_parameter_document(path.read_text(encoding="utf-8"), contract)
        except (OSError, UnicodeError, ParameterContractError) as error:
            raise SystemExit(f"[ERROR] {path}: {error}") from error
        print(f"[OK] Dingqiao common parameter contract: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
