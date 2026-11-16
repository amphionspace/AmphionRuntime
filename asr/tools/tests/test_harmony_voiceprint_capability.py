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

    def test_short_command_final_score_uses_segment_templates_but_hops_do_not(self) -> None:
        """缺陷 #97 第二轮：final 打分用整文件 + 2 s 分段模板，流式确认与边界校验只用整文件模板。

        客户「OKOK」有效语音不到 1 s，对 8 s 整文件模板只有 0.370（刚过 0.35）；按 2 s 窗切出的
        分段模板把它抬到 0.444。短对短匹配同样抬高非机主短窗（1.5 s 最高 0.20 → 0.33），所以
        分段模板不得进入 hop/边界打分，否则非机主更容易被"确认"而绕过 0.45 下沿。
        """
        enroller = (REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerEnroller.ets").read_text(encoding="utf-8")
        store = (REPO_ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/VoiceprintStore.ets").read_text(encoding="utf-8")
        sdk = SDK.read_text(encoding="utf-8")
        runtime = (REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets").read_text(encoding="utf-8")

        self.assertIn("enrollFileSegmentTemplates(audioPaths: string[])", enroller)
        self.assertIn("SEGMENT_TEMPLATE_SECONDS: number = 2.0", enroller)
        self.assertIn("segment-templates.bin", store)
        self.assertIn("loadSegmentTemplates(id: string)", store)
        # 注册时生成并持久化；加载时并入 final 模板，并以独立接口交给会话。
        self.assertIn("enroller.enrollFileSegmentTemplates(params.samplePaths)", sdk)
        self.assertIn("store.saveVoiceprint(params.samplePaths, embedding, templates, segmentTemplates)", sdk)
        self.assertIn("store.loadSegmentTemplates(voiceprintIds[i])", sdk)
        self.assertEqual(sdk.count("setTargetSpeakerFinalTemplates(this.voiceprintFinalTemplates)"), 2)
        # Runtime：final 路径带 forFinal=true；hop/边界路径不带。
        self.assertIn("setTargetSpeakerFinalTemplates(templates: Float32Array[])", runtime)
        self.assertIn("this.targetSpeakerFinalTemplates = []", runtime)
        for final_call in (
            "await this.scoreSamplesAsync(samples, true)",
            "await this.scoreSamplesAsync(selection.samples, true)",
            "this.scoreSamples(selection.samples, true)",
            "this.targetSimilarity(embedding, targetSpeaker, true)",
        ):
            self.assertIn(final_call, runtime, final_call)
        self.assertIn("await this.scoreSamplesAsync(request.samples)", runtime)
        self.assertIn("this.scoreSamples(this.speakerPcmBuffers.speakerVadTail(winSamples))", runtime)
        self.assertNotIn("scoreSamplesBatchAsync(requests, true)", runtime)
        self.assertIn("if (!forFinal) this.lastSpeakerVadScore = score;", runtime)


if __name__ == "__main__":
    unittest.main()
