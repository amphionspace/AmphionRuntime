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

    def test_sdk_only_packaging_does_not_require_demo_build_identity(self) -> None:
        script = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "build_identity = {} if sdk_only else json.loads",
            script,
        )

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
