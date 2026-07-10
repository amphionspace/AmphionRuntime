#!/usr/bin/env python3

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_license_device_set.py")


def device_hash(device_id: str, salt_id: str) -> str:
    value = f"{device_id.strip().upper()}{salt_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest().upper()


class VerifyLicenseDeviceSetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.license_path = self.root / "license.lic"
        self.device_path = self.root / "devices.txt"
        self.salt_id = "test-salt"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_license(self, device_ids: list[str], duplicate_hash: bool = False) -> None:
        hashes = [device_hash(device_id, self.salt_id) for device_id in device_ids]
        if duplicate_hash:
            hashes.append(hashes[0])
        payload = json.dumps(
            {
                "authorizedDeviceHashes": hashes,
                "deviceIdSaltId": self.salt_id,
            }
        ).encode("utf-8")
        envelope = {"payload_b64": base64.b64encode(payload).decode("ascii")}
        self.license_path.write_text(json.dumps(envelope), encoding="utf-8")

    def run_verifier(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--license",
                str(self.license_path),
                "--device-id-file",
                str(self.device_path),
            ],
            capture_output=True,
            check=False,
            text=True,
        )

    def test_accepts_exact_unique_set(self) -> None:
        self.write_license(["DEVICE-A", "DEVICE-B"])
        self.device_path.write_text("device-b\nDEVICE-A\n", encoding="utf-8")

        result = self.run_verifier()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2 unique device bindings", result.stdout)

    def test_rejects_duplicate_device_ids(self) -> None:
        self.write_license(["DEVICE-A", "DEVICE-B"])
        self.device_path.write_text("DEVICE-A\ndevice-a\n", encoding="utf-8")

        result = self.run_verifier()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate identifiers", result.stderr)

    def test_rejects_same_count_with_different_device(self) -> None:
        self.write_license(["DEVICE-A", "DEVICE-B"])
        self.device_path.write_text("DEVICE-A\nDEVICE-C\n", encoding="utf-8")

        result = self.run_verifier()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("do not exactly match", result.stderr)

    def test_rejects_duplicate_hashes_in_license(self) -> None:
        self.write_license(["DEVICE-A"], duplicate_hash=True)
        self.device_path.write_text("DEVICE-A\n", encoding="utf-8")

        result = self.run_verifier()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate authorized device hashes", result.stderr)

    def test_accepts_unbound_license_with_empty_list(self) -> None:
        self.write_license([])
        self.device_path.write_text("# intentionally unbound\n", encoding="utf-8")

        result = self.run_verifier()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no device binding", result.stdout)

    def test_accepts_unbound_license_without_list_file(self) -> None:
        self.write_license([])

        result = self.run_verifier()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_unbound_license_with_populated_list(self) -> None:
        self.write_license([])
        self.device_path.write_text("DEVICE-A\n", encoding="utf-8")

        result = self.run_verifier()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unbound license", result.stderr)


if __name__ == "__main__":
    unittest.main()
