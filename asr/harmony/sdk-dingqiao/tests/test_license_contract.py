from pathlib import Path
import re
import unittest


HARMONY_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SOURCE = HARMONY_ROOT / "sdk/src/main/ets/com/amphion/asr/Runtime.ets"
LICENSE_SOURCE = HARMONY_ROOT / "sdk/src/main/ets/com/amphion/asr/License.ets"
DINGQIAO_SOURCE = (
    HARMONY_ROOT
    / "sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)


class HarmonyLicenseContractTest(unittest.TestCase):
    def test_delivery_version_controls_are_enabled(self) -> None:
        source = RUNTIME_SOURCE.read_text(encoding="utf-8")

        self.assertRegex(source, r"SDK_VERSION:\s*string\s*=\s*'0\.2\.0-harmony'")
        self.assertRegex(source, r"SDK_MAJOR:\s*number\s*=\s*1;")
        self.assertRegex(source, r"SDK_RELEASE_DATE:\s*string\s*=\s*'2026-07-13'")

    def test_certificate_binding_fails_closed_when_host_digest_is_missing(self) -> None:
        source = LICENSE_SOURCE.read_text(encoding="utf-8")

        self.assertNotIn(
            "boundCert.length > 0 && hostCert.length > 0 && boundCert !== hostCert",
            source,
        )
        self.assertEqual(
            2,
            source.count("boundCert.length > 0 && hostCert.length === 0"),
        )
        self.assertEqual(
            2,
            source.count("boundCert.length > 0 && boundCert !== hostCert"),
        )

    def test_sdk_major_is_required_and_must_match(self) -> None:
        source = LICENSE_SOURCE.read_text(encoding="utf-8")

        self.assertEqual(
            2,
            source.count("sdkMajor > 0 && claimSdkMajor !== sdkMajor"),
        )
        self.assertNotIn("claimSdkMajor > 0 && sdkMajor > 0", source)

    def test_public_sdk_passes_installed_host_certificate_fingerprint(self) -> None:
        source = DINGQIAO_SOURCE.read_text(encoding="utf-8")

        self.assertIn("import { bundleManager } from '@kit.AbilityKit';", source)
        self.assertIn("bundleManager.getBundleInfoForSelfSync(", source)
        self.assertIn("bundleManager.BundleFlag.GET_BUNDLE_INFO_WITH_SIGNATURE_INFO", source)
        self.assertRegex(
            source,
            re.compile(
                r"fingerprint\s*=\s*bundleInfo\.signatureInfo\.fingerprint\.trim\(\)"
            ),
        )
        self.assertIn("identity.signingCertDigest = fingerprint;", source)
        self.assertIn(
            "options.signingCertDigest = hostIdentity.signingCertDigest;",
            source,
        )
        # Guard against a future regression that starts an asynchronous query but immediately
        # returns empty options to the caller.
        self.assertNotIn("bundleManager.getBundleInfoForSelf(", source)


if __name__ == "__main__":
    unittest.main()
