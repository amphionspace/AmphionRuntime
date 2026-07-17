import json
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
IDENTITY = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/RuntimeIdentity.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
LICENSE = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/License.ets"


class HarmonyRuntimeIdentityTest(unittest.TestCase):
    def run_identity(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{
              HARMONY_SDK_MAJOR,
              HARMONY_SDK_RELEASE_DATE,
              HARMONY_SDK_VERSION,
              LicenseIdentityFailure,
              evaluateLicenseIdentity,
            }} from {IDENTITY.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_runtime_identity_matches_delivery_version(self) -> None:
        self.run_identity(
            """
            assert.equal(HARMONY_SDK_VERSION, '0.2.6');
            assert.equal(HARMONY_SDK_MAJOR, 1);
            assert.equal(HARMONY_SDK_RELEASE_DATE, '2026-07-16');
            """
        )

        runtime = RUNTIME.read_text(encoding="utf-8")
        license_source = LICENSE.read_text(encoding="utf-8")
        self.assertIn("from './RuntimeIdentity'", runtime)
        self.assertIn("from './RuntimeIdentity'", license_source)
        self.assertNotIn("0.2.0-harmony", runtime)

    def test_license_major_and_maintenance_boundaries_fail_closed(self) -> None:
        self.run_identity(
            """
            assert.equal(
              evaluateLicenseIdentity(2, HARMONY_SDK_MAJOR, '2027-01-01', HARMONY_SDK_RELEASE_DATE),
              LicenseIdentityFailure.SDK_MAJOR_MISMATCH,
            );
            assert.equal(
              evaluateLicenseIdentity(1, HARMONY_SDK_MAJOR, '2026-07-15', HARMONY_SDK_RELEASE_DATE),
              LicenseIdentityFailure.MAINTENANCE_EXPIRED,
            );
            assert.equal(
              evaluateLicenseIdentity(1, HARMONY_SDK_MAJOR, '2026-07-16', HARMONY_SDK_RELEASE_DATE),
              LicenseIdentityFailure.NONE,
            );
            assert.equal(
              evaluateLicenseIdentity(1, HARMONY_SDK_MAJOR, '2026-07-17', HARMONY_SDK_RELEASE_DATE),
              LicenseIdentityFailure.NONE,
            );
            """
        )

    def test_native_type_package_and_locks_match_runtime_version(self) -> None:
        for relative in (
            "asr/harmony/oh-package.json5",
            "asr/harmony/sdk/oh-package.json5",
            "asr/harmony/sdk-police/oh-package.json5",
            "asr/harmony/sdk-dingqiao/oh-package.json5",
            "asr/harmony/sdk/src/main/cpp/types/libamphion_asr/oh-package.json5",
        ):
            manifest = json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "0.2.6", relative)

        # Lockfiles are generated/ignored by ohpm. When present, they must not retain stale native
        # identity, but a clean checkout does not need generated files for this gate to pass.
        for relative in (
            "asr/harmony/sdk/oh-package-lock.json5",
            "asr/harmony/sdk-police/oh-package-lock.json5",
            "asr/harmony/sdk-dingqiao/oh-package-lock.json5",
        ):
            lock_path = REPO_ROOT / relative
            if not lock_path.exists():
                continue
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            native_packages = [
                package
                for package in lock["packages"].values()
                if package.get("name") == "libamphion_asr.so"
            ]
            self.assertTrue(native_packages, relative)
            self.assertTrue(
                all(package["version"] == "0.2.6" for package in native_packages),
                relative,
            )


if __name__ == "__main__":
    unittest.main()
