from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


class ReleaseDefaultsTest(unittest.TestCase):
    def test_ci_discovers_all_harmony_contracts_and_runs_finish_compat_gate_tests(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")

        self.assertIn(
            "python3 -m unittest discover -s asr/tools/tests -p 'test_harmony_*.py' -v",
            workflow,
        )
        self.assertIn(
            "delivery.harmony-dingqiao.delivery.test_run_finish_compat_release_gate",
            workflow,
        )

    def test_asr_contracts_checkout_keeps_history_for_police_parity(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        contracts = workflow.split("  asr-contracts:", 1)[1].split("  android-aar:", 1)[0]

        self.assertIn("fetch-depth: 0", contracts)

    def test_android_native_cache_is_exact_verified_and_only_skips_native_build(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        android = workflow.split("  android-aar:", 1)[1].split("  ci-result:", 1)[0]
        native_cache = android.split("- name: Restore verified native artifacts", 1)[1].split(
            "- name: Cache Gradle", 1
        )[0]

        self.assertIn("steps.native-fingerprint.outputs.fingerprint", native_cache)
        self.assertNotIn("restore-keys:", native_cache)
        self.assertIn("steps.native-cache.outputs.cache-hit == 'true'", android)
        self.assertIn("steps.native-cache.outputs.cache-hit != 'true'", android)
        self.assertIn("android_native_cache.py verify", android)
        self.assertIn("android_native_cache.py create-manifest", android)
        self.assertIn("env.NATIVE_CACHE_MANIFEST", native_cache)
        self.assertIn("native-cache-manifest.json", workflow)
        self.assertIn('$ANDROID_HOME/cmake/${{ env.CMAKE_VERSION }}/bin', android)
        self.assertIn("asr.tools.tests.test_android_native_cache", workflow)

        native_build = android.index("bash asr/tools/04_build_android_so.sh arm64-v8a")
        gradle_build = android.index("Gradle assemble + unit test")
        self.assertLess(native_build, gradle_build)
        gradle_section = android[gradle_build:]
        self.assertNotIn("cache-hit", gradle_section)

    def test_finish_compat_release_gate_is_part_of_the_project_working_agreement(self) -> None:
        agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        device_stress = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/DEVICE_STRESS.md"
        ).read_text(encoding="utf-8")

        command = "delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py"
        self.assertIn(command, agreement)
        self.assertIn(command, device_stress)
        self.assertIn("FINISH_COMPATIBILITY_POSTMORTEM.md", device_stress)

    def test_prepack_is_disabled_by_default_across_public_harmony_layers(self) -> None:
        core = (
            REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets"
        ).read_text(encoding="utf-8")
        dingqiao = (
            REPO_ROOT
            / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/"
            "SpeechRecognizeSdk.ets"
        ).read_text(encoding="utf-8")
        docs = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/语音识别SDK接口.md"
        ).read_text(encoding="utf-8")

        self.assertIn("disablePrepack: boolean = true;", core)
        self.assertIn(
            "compatibleBooleanParam(params.extraParams, 'disablePrepack', true)",
            dingqiao,
        )
        self.assertIn("| `disablePrepack` | `boolean/number/string` | `true` |", docs)

    def test_sdk_only_packaging_requires_verified_har_source_identity(self) -> None:
        script = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('python3 "$SCRIPT_DIR/harmony_build_identity.py" --verify "$BUILD_IDENTITY"', script)
        self.assertIn("build_identity = json.loads", script)
        self.assertIn('"verified_source_identity"', script)

    def test_sdk_only_changelog_combines_controlled_notes_and_commit_trace(self) -> None:
        script = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("docs/CHANGELOG.md", script)
        self.assertIn(".CHANGELOG_COMMITS.md", script)
        self.assertIn("controlled release notes missing", script)
        self.assertIn("## 源码提交明细", script)

    def test_speaker_vad_defaults_match_sdk_demo_and_public_docs(self) -> None:
        sdk = (
            REPO_ROOT
            / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/"
            "SpeechRecognizeSdk.ets"
        ).read_text(encoding="utf-8")
        demo = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/"
            "Index.ets"
        ).read_text(encoding="utf-8")
        docs = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/语音识别SDK接口.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadThreshold', 0.35), -1.0, 1.0)",
            sdk,
        )
        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadWindowMs', 1500), 500, 5000)",
            sdk,
        )
        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadHopMs', 500), 100, 2000)",
            sdk,
        )
        self.assertIn("SPEAKER_VAD_THRESHOLD = 0.35", demo)
        self.assertIn("SPEAKER_VAD_WINDOW_MS = 1500", demo)
        self.assertIn("SPEAKER_VAD_HOP_MS = 500", demo)
        self.assertIn("| `speakerVadThreshold` | `number/string` | `0.35` |", docs)
        self.assertIn("| `speakerVadWindowMs` | `number/string` | `1500` |", docs)
        self.assertIn("| `speakerVadHopMs` | `number/string` | `500` |", docs)


if __name__ == "__main__":
    unittest.main()
