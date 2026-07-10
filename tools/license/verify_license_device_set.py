#!/usr/bin/env python3
"""Verify that a device-id file exactly matches a license device hash set."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path


def _normalize_hex(value: str) -> str:
    return value.replace(":", "").replace(" ", "").upper()


def _device_hash(device_id: str, salt_id: str) -> str:
    value = f"{device_id.strip().upper()}{salt_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest().upper()


def _load_claims(license_path: Path) -> dict[str, object]:
    try:
        envelope = json.loads(license_path.read_text(encoding="utf-8"))
        payload = base64.b64decode(envelope["payload_b64"], validate=True)
        claims = json.loads(payload.decode("utf-8"))
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[ERROR] invalid license envelope: {exc}") from exc
    if not isinstance(claims, dict):
        raise SystemExit("[ERROR] license payload must be a JSON object")
    return claims


def _load_device_ids(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"[ERROR] cannot read device-id file: {path}") from exc

    device_ids = [line.strip().upper() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if len(device_ids) != len(set(device_ids)):
        raise SystemExit("[ERROR] authorized device list contains duplicate identifiers")
    return device_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--license", required=True, type=Path)
    parser.add_argument("--device-id-file", required=True, type=Path)
    args = parser.parse_args()

    claims = _load_claims(args.license)
    raw_hashes = claims.get("authorizedDeviceHashes", [])
    if not isinstance(raw_hashes, list) or not all(isinstance(value, str) for value in raw_hashes):
        raise SystemExit("[ERROR] authorizedDeviceHashes must be a string array")

    authorized_hashes = [_normalize_hex(value) for value in raw_hashes]
    if len(authorized_hashes) != len(set(authorized_hashes)):
        raise SystemExit("[ERROR] license contains duplicate authorized device hashes")
    if not authorized_hashes:
        if args.device_id_file.exists() and _load_device_ids(args.device_id_file):
            raise SystemExit("[ERROR] unbound license does not match a populated authorized device list")
        print("[OK] license has no device binding")
        return

    device_ids = _load_device_ids(args.device_id_file)
    salt_id = claims.get("deviceIdSaltId", "")
    if not isinstance(salt_id, str):
        raise SystemExit("[ERROR] deviceIdSaltId must be a string")
    computed_hashes = {_device_hash(device_id, salt_id) for device_id in device_ids}
    authorized_set = set(authorized_hashes)
    if computed_hashes != authorized_set or len(device_ids) != len(authorized_hashes):
        raise SystemExit("[ERROR] license device hashes do not exactly match the authorized device list")

    print(f"[OK] verified {len(device_ids)} unique device bindings")


if __name__ == "__main__":
    main()
