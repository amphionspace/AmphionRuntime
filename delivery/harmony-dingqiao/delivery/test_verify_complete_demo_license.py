from __future__ import annotations

import base64
from datetime import date
import json
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .verify_complete_demo_license import (
    PortableDemoError,
    verify_license,
    verify_profile_result,
)


def license_envelope(claims: dict, private_key: ec.EllipticCurvePrivateKey) -> bytes:
    payload = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    return json.dumps(
        {
            "alg": "SHA256withECDSA",
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "sig_b64": base64.b64encode(signature).decode("ascii"),
        },
        separators=(",", ":"),
    ).encode("utf-8")


class CompleteDemoLicenseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        public_der = self.private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.public_key_b64 = base64.b64encode(public_der).decode("ascii")
        self.claims = {
            "authorizedDeviceHashes": [],
            "expiresAt": "2026-12-31",
            "features": ["ASR"],
            "maintenanceUntil": "2026-12-31",
            "sdkMajor": 1,
        }

    def verify(self, claims: dict | None = None, key=None) -> dict:
        signer = key or self.private_key
        return verify_license(
            license_envelope(claims or self.claims, signer),
            self.public_key_b64,
            1,
            date(2026, 8, 24),
            date(2026, 8, 24),
        )

    def test_accepts_signed_unbound_demo_license(self) -> None:
        self.assertEqual([], self.verify()["authorizedDeviceHashes"])

    def test_rejects_invalid_signature(self) -> None:
        with self.assertRaisesRegex(PortableDemoError, "signature"):
            self.verify(key=ec.generate_private_key(ec.SECP256R1()))

    def test_rejects_device_bound_expired_or_featureless_license(self) -> None:
        invalid = (
            ({**self.claims, "authorizedDeviceHashes": ["device-hash"]}, "device-bound"),
            ({**self.claims, "expiresAt": "2026-08-23"}, "expired"),
            ({**self.claims, "features": ["TTS"]}, "ASR feature"),
        )
        for claims, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex(PortableDemoError, message):
                    self.verify(claims)

    def test_accepts_release_profile_without_devices(self) -> None:
        verify_profile_result(
            {
                "verifiedPassed": True,
                "content": {
                    "type": "release",
                    "bundle-info": {"bundle-name": "com.amphion.asr.harmony.demo"},
                },
            },
            "com.amphion.asr.harmony.demo",
        )

    def test_rejects_debug_or_device_limited_profile(self) -> None:
        for content, message in (
            ({"type": "debug", "bundle-info": {"bundle-name": "demo"}}, "debug profile"),
            ({"type": "release", "bundle-info": {"bundle-name": "demo"},
              "debug-info": {"device-ids": ["device"]}}, "device allowlist"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(PortableDemoError, message):
                    verify_profile_result(
                        {"verifiedPassed": True, "content": content}, "demo"
                    )


if __name__ == "__main__":
    unittest.main()
