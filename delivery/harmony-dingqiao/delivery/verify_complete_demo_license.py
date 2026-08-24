#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timezone
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


LICENSE_ENTRY = "resources/rawfile/amphion-license.lic"
REPO_ROOT = Path(__file__).resolve().parents[3]
LICENSE_SOURCE = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/License.ets"
RUNTIME_IDENTITY = (
    REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/RuntimeIdentity.ts"
)
DEVECO_HOME = Path(os.environ.get("DEVECO_STUDIO_HOME", "/Applications/DevEco-Studio.app/Contents"))
DEFAULT_JAVA = DEVECO_HOME / "jbr/Contents/Home/bin/java"
DEFAULT_SIGN_TOOL = (
    DEVECO_HOME / "sdk/default/openharmony/toolchains/lib/hap-sign-tool.jar"
)


class PortableDemoError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that a complete-delivery Demo is signed for distribution and usable."
    )
    parser.add_argument("--hap", required=True, type=Path)
    parser.add_argument("--java-bin", type=Path, default=DEFAULT_JAVA)
    parser.add_argument("--hap-sign-tool", type=Path, default=DEFAULT_SIGN_TOOL)
    return parser.parse_args()


def source_value(path: Path, pattern: str, label: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    if match is None:
        raise PortableDemoError(f"cannot read {label} from {path.name}")
    return match.group(1)


def verify_license(license_bytes: bytes, public_key_b64: str, sdk_major: int,
                   sdk_release_date: date, today: date | None = None) -> dict:
    try:
        envelope = json.loads(license_bytes)
        payload = base64.b64decode(envelope["payload_b64"], validate=True)
        signature = base64.b64decode(envelope["sig_b64"], validate=True)
        claims = json.loads(payload)
        public_key = serialization.load_der_public_key(
            base64.b64decode(public_key_b64, validate=True)
        )
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            raise PortableDemoError("embedded SDK license key is not EC")
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise PortableDemoError("embedded Demo license signature is invalid") from error
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        raise PortableDemoError(f"embedded Demo license is malformed: {error}") from error

    features = {str(item).strip().upper() for item in claims.get("features", [])}
    if "ASR" not in features:
        raise PortableDemoError("embedded Demo license has no ASR feature")
    devices = claims.get("authorizedDeviceHashes")
    if devices not in (None, []):
        raise PortableDemoError("embedded Demo license is device-bound")
    if str(claims.get("signingCertDigest") or "").strip():
        raise PortableDemoError("embedded Demo license is signing-certificate-bound")

    current = today or datetime.now(timezone.utc).date()
    expires_at = str(claims.get("expiresAt") or "").strip()
    if not expires_at:
        raise PortableDemoError("embedded Demo license has no expiry")
    if current > date.fromisoformat(expires_at):
        raise PortableDemoError("embedded Demo license is expired")

    licensed_major = int(claims.get("sdkMajor", -1))
    if licensed_major > 0 and sdk_major > 0 and licensed_major != sdk_major:
        raise PortableDemoError("embedded Demo license SDK major does not match")
    maintenance_until = str(claims.get("maintenanceUntil") or "").strip()
    if maintenance_until and sdk_release_date > date.fromisoformat(maintenance_until):
        raise PortableDemoError("embedded Demo license maintenance window does not cover this SDK")
    return claims


def verify_profile_result(profile_result: dict, expected_bundle: str) -> None:
    if profile_result.get("verifiedPassed") is not True:
        raise PortableDemoError("embedded HAP profile signature did not verify")
    content = profile_result.get("content", {})
    if content.get("bundle-info", {}).get("bundle-name") != expected_bundle:
        raise PortableDemoError("embedded HAP profile belongs to another bundle")
    if content.get("type") != "release":
        raise PortableDemoError("embedded HAP uses a debug profile and is device-limited")
    device_ids = (content.get("debug-info") or {}).get("device-ids") or []
    if device_ids:
        raise PortableDemoError("embedded HAP profile contains a device allowlist")


def verify_hap_profile(hap: Path, java_bin: Path, sign_tool: Path,
                       expected_bundle: str) -> None:
    if not java_bin.is_file() or not sign_tool.is_file():
        raise PortableDemoError("DevEco Java or hap-sign-tool is missing")
    with tempfile.TemporaryDirectory(prefix="amphion-portable-demo-") as directory:
        root = Path(directory)
        verify_app = subprocess.run(
            [str(java_bin), "-jar", str(sign_tool), "verify-app", "-inFile", str(hap),
             "-outCertChain", str(root / "cert-chain.cer"),
             "-outProfile", str(root / "profile.p7b")],
            capture_output=True, check=False, text=True,
        )
        if verify_app.returncode != 0 or "verify-app success" not in verify_app.stdout:
            raise PortableDemoError("HAP application signature did not verify")
        verify_profile = subprocess.run(
            [str(java_bin), "-jar", str(sign_tool), "verify-profile",
             "-inFile", str(root / "profile.p7b"),
             "-outFile", str(root / "profile.json")],
            capture_output=True, check=False, text=True,
        )
        if verify_profile.returncode != 0:
            raise PortableDemoError("HAP profile signature did not verify")
        verify_profile_result(
            json.loads((root / "profile.json").read_text(encoding="utf-8")), expected_bundle
        )


def main() -> int:
    args = parse_args()
    try:
        with zipfile.ZipFile(args.hap) as archive:
            license_bytes = archive.read(LICENSE_ENTRY)
            module = json.loads(archive.read("module.json"))
        bundle_name = module.get("app", {}).get("bundleName")
        if not isinstance(bundle_name, str) or not bundle_name:
            raise PortableDemoError("HAP module has no bundle name")
        public_key = source_value(
            LICENSE_SOURCE, r"LICENSE_PUBLIC_KEY_B64: string = '([^']+)'", "license public key"
        )
        sdk_major = int(source_value(
            RUNTIME_IDENTITY, r"HARMONY_SDK_MAJOR: number = ([0-9]+)", "SDK major"
        ))
        release_date = date.fromisoformat(source_value(
            RUNTIME_IDENTITY,
            r"HARMONY_SDK_RELEASE_DATE: string = '([0-9]{4}-[0-9]{2}-[0-9]{2})'",
            "SDK release date",
        ))
        verify_license(license_bytes, public_key, sdk_major, release_date)
        verify_hap_profile(args.hap, args.java_bin, args.hap_sign_tool, bundle_name)
    except (PortableDemoError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        print(f"[ERROR] complete-delivery Demo is not portable: {error}", file=sys.stderr)
        return 1
    print("[OK] complete-delivery Demo has a valid portable license and release profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
