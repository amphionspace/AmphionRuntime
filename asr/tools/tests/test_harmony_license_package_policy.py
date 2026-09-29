import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ASR_POLICY = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/RuntimePackagePolicy.ts"
TTS_POLICY = ROOT / "tts/harmony/sdk/src/main/ets/RuntimePackagePolicy.ts"
ASR_LICENSE = ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/License.ets"
TTS_LICENSE = ROOT / "tts/harmony/sdk/src/main/ets/License.ets"
TTS_API = ROOT / "tts/harmony/sdk/src/main/ets/TextToSpeechApi.ets"


class HarmonyLicensePackagePolicyTest(unittest.TestCase):
    def test_asr_and_tts_share_multi_package_and_compatibility_semantics(self) -> None:
        for policy in (ASR_POLICY, TTS_POLICY):
            script = textwrap.dedent(
                f"""
                import assert from 'node:assert/strict';
                import {{ applicationMatches }} from {policy.as_uri()!r};
                const allowed = ['ai.fourhz.primary', 'ai.fourhz.secondary'];
                assert.equal(applicationMatches('allowlist', allowed[0], allowed, allowed[0]), true);
                assert.equal(applicationMatches('allowlist', allowed[0], allowed, allowed[1]), true);
                assert.equal(applicationMatches('allowlist', allowed[0], allowed, 'ai.fourhz.other'), false);
                assert.equal(applicationMatches('none', allowed[0], [], 'ai.customer.any'), true);
                assert.equal(applicationMatches('', allowed[0], [], 'ai.customer.legacy'), true);
                assert.equal(applicationMatches('unknown', '', [], 'ai.customer.any'), false);
                """
            )
            subprocess.run(
                ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
                cwd=ROOT,
                check=True,
            )

    def test_both_license_verifiers_apply_the_signed_policy(self) -> None:
        for source in (ASR_LICENSE, TTS_LICENSE):
            text = source.read_text(encoding="utf-8")
            self.assertIn("stringValue(claims, 'applicationBindingMode')", text)
            self.assertIn("stringArray(claims, 'bundleNames')", text)
            self.assertIn("AsrErrorCode.LICENSE_APP_MISMATCH", text)
            self.assertNotIn("boundCert.length > 0 && hostCert.length > 0", text)

    def test_tts_supplies_real_host_identity_to_the_verifier(self) -> None:
        text = TTS_API.read_text(encoding="utf-8")
        self.assertIn("TextToSpeechSdk.context?.applicationInfo.name", text)
        self.assertIn("bundleManager.getBundleInfoForSelfSync", text)
        self.assertIn("bundleInfo.signatureInfo.fingerprint", text)
        self.assertIn("bundleName,\n      signingCertDigest,", text)


if __name__ == "__main__":
    unittest.main()
