import re
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CAPABILITY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/VoiceprintCapability.ts"
)
SDK = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
RECOGNITION_CONFIG = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RecognitionConfig.ets"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
TYPES = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets"
TARGET_CONFIG_POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/TargetSpeakerConfigPolicy.ts"
)


class HarmonyVoiceprintCapabilityTest(unittest.TestCase):
    def test_voiceprint_ids_preconfigure_runtime_capability(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ hasVoiceprintCapability }} from {CAPABILITY.as_uri()!r};

            assert.equal(hasVoiceprintCapability(false, false, 0), false);
            assert.equal(hasVoiceprintCapability(true, false, 0), true);
            assert.equal(hasVoiceprintCapability(false, true, 0), true);
            assert.equal(hasVoiceprintCapability(false, false, 1), true);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_adapter_passes_configured_initial_confirmation_capability(self) -> None:
        source = SDK.read_text(encoding="utf-8")
        self.assertIn(
            "hasVoiceprintCapability(verify, speakerVad, voiceprintIds.length)",
            source,
        )
        self.assertIn(
            "buildSessionConfig(params, configureTarget, configureTarget)",
            source,
        )
        self.assertNotIn(
            "buildSessionConfig(params, configureTarget, verify || speakerVad)",
            source,
        )

    def test_core_caps_requested_grace_at_target_minimum_segment(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn(
            "Math.round(config.targetSpeaker.minSegSec * 1000)",
            source,
        )
        self.assertIn(
            "Math.min(\n      requestedConfirmationGraceMs, maxConfirmationGraceMs)",
            source,
        )

    def test_voiceprint_verification_is_score_only_in_customer_adapter(self) -> None:
        source = RECOGNITION_CONFIG.read_text(encoding="utf-8")
        target_config = source.split(
            "function buildTargetSpeakerConfig(", 1
        )[1].split("function buildSpeakerVadConfig", 1)[0]

        self.assertIn("cfg.threshold = -1.0", target_config)
        self.assertIn("cfg.minSegSec = 0", target_config)

    def test_voiceprint_extractor_threads_are_shared_and_above_one(self) -> None:
        """机主确认前嵌入推理与 ASR 解码串行，单线程打分抬高 endpoint→final（缺陷 #98）。

        手机 80 同录音实测 1 → 4 线程：单次 inferMs median 224 → 118，换人切分句的
        endpoint→final 1613 → 1212 ms。同时 extractor 池按 `${modelPath}|${numThreads}`
        建键：注册、识别和预加载取值不一致会让同一个 ~38 MB 的 eres2net 在进程里存两份。
        """
        config = RECOGNITION_CONFIG.read_text(encoding="utf-8")
        sdk = SDK.read_text(encoding="utf-8")

        declaration = re.search(
            r"export const SPEAKER_EXTRACTOR_THREADS: number = (\d+);", config
        )
        self.assertIsNotNone(
            declaration, "adapter must declare one speaker extractor thread count"
        )
        threads = int(declaration.group(1))
        self.assertGreater(
            threads, 1, "single-threaded speaker scoring serialises ahead of ASR decode"
        )
        self.assertLessEqual(threads, 8, "TargetSpeakerConfig.numThreads is capped at 8")

        target_config = config.split("function buildTargetSpeakerConfig(", 1)[1].split(
            "function buildSpeakerVadConfig", 1
        )[0]
        self.assertIn("cfg.numThreads = SPEAKER_EXTRACTOR_THREADS;", target_config)

        # eres2net(bundledPath) 的每个获取点都必须用同一个常量，否则池键分裂。
        bundled = [
            line.strip()
            for line in sdk.splitlines()
            if "getOrCreateSpeakerExtractor(" in line or "new SpeakerEnroller(" in line
        ]
        self.assertTrue(bundled, "adapter must acquire the pooled extractor")
        for line in bundled:
            if "identityModelPath" in line:
                continue  # campplus 角色分离身份模型是另一个 modelPath，另算一套池键
            self.assertNotRegex(
                line,
                r",\s*1[,)]",
                f"bundled eres2net acquisition must share the thread constant: {line}",
            )

    def test_target_speaker_minimum_defaults_to_zero_and_allows_zero(self) -> None:
        source = TYPES.read_text(encoding="utf-8")
        self.assertIn("minSegSec: number = 0;", source)
        self.assertIn("isValidSpeakerMinimumSegment(config.minSegSec)", source)
        self.assertIn("minSegSec must be finite and >= 0", source)
        self.assertNotIn("config.minSegSec <= 0", source)

    def test_target_speaker_minimum_requires_a_non_negative_finite_value(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ isValidSpeakerMinimumSegment }} from {TARGET_CONFIG_POLICY.as_uri()!r};

            assert.equal(isValidSpeakerMinimumSegment(0), true);
            assert.equal(isValidSpeakerMinimumSegment(1.5), true);
            assert.equal(isValidSpeakerMinimumSegment(-0.001), false);
            assert.equal(isValidSpeakerMinimumSegment(Number.NaN), false);
            assert.equal(isValidSpeakerMinimumSegment(Number.POSITIVE_INFINITY), false);
            assert.equal(isValidSpeakerMinimumSegment(Number.NEGATIVE_INFINITY), false);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )


if __name__ == "__main__":
    unittest.main()
