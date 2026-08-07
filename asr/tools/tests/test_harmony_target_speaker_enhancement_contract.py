import pathlib
import re
import subprocess
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SDK = ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
ENHANCER = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancer.ets"
)
CONFIG = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementConfig.ts"
)
DEVICE_STRESS = (
    ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"
)
DEMO = (
    ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets"
)


class HarmonyTargetSpeakerEnhancementContractTest(unittest.TestCase):
    def test_missing_separator_reports_the_required_packaged_asset(self) -> None:
        source = ENHANCER.read_text(encoding="utf-8")
        self.assertIn("try {", source)
        self.assertIn("target speaker enhancement model is not bundled", source)
        self.assertIn("amphion-dingqiao/convtasnet_16k.ort", source)

    def test_separator_model_is_pooled_until_sdk_model_unload(self) -> None:
        enhancer = ENHANCER.read_text(encoding="utf-8")
        sdk = SDK.read_text(encoding="utf-8")
        self.assertIn("loadTargetSpeakerEnhancementModel", enhancer)
        self.assertIn("isTargetSpeakerEnhancementModelLoaded", enhancer)
        self.assertIn("static unloadModel(): void", enhancer)
        self.assertIn("unloadTargetSpeakerEnhancementModel", enhancer)
        self.assertGreaterEqual(sdk.count("TargetSpeakerEnhancer.unloadModel();"), 2)

    def test_explicit_async_preload_moves_enhancement_load_off_start_listening(self) -> None:
        enhancer = ENHANCER.read_text(encoding="utf-8")
        sdk = SDK.read_text(encoding="utf-8")
        native = (
            ROOT / "asr/harmony/sdk/src/main/cpp/target_speaker_enhancer.cpp"
        ).read_text(encoding="utf-8")
        types = (
            ROOT / "asr/harmony/sdk/src/main/cpp/types/libamphion_asr/index.d.ts"
        ).read_text(encoding="utf-8")
        demo = DEMO.read_text(encoding="utf-8")
        self.assertIn("preloadTargetSpeakerEnhancementModelAsync", native)
        self.assertIn("preloadTargetSpeakerEnhancementModelAsync", types)
        self.assertIn("static async preload", enhancer)
        self.assertIn("static async preloadTargetSpeakerEnhancementModel", sdk)
        self.assertIn("getOrCreateSpeakerExtractorAsync", sdk)
        self.assertIn("preloadTargetSpeakerEnhancement", demo)
        self.assertIn("private targetSpeakerPreloadTask?: Promise<boolean>;", demo)
        self.assertIn("private async startSessionWhenEnhancementReady", demo)
        self.assertIn("const preloadTask = this.targetSpeakerPreloadTask;", demo)
        self.assertIn("await preloadTask;", demo)
        self.assertNotIn("this.loading = true;\n    this.loadingHint = '正在后台准备目标说话人增强模型", demo)

    def test_device_evidence_records_target_speaker_inputs_and_lifecycle(self) -> None:
        source = DEVICE_STRESS.read_text(encoding="utf-8")
        for function_name in (
            "runTargetSpeakerEnhancementCycle",
            "runTargetSpeakerEnhancementOnStartCycle",
            "runTargetSpeakerEnhancementCancelCycle",
        ):
            start = source.index(f"async function {function_name}")
            next_function = re.search(r"\n(?:async )?function ", source[start + 1 :])
            end = start + 1 + next_function.start() if next_function else len(source)
            body = source[start : end if end >= 0 else len(source)]
            self.assertIn("result.voiceprintIdCount = 1", body, function_name)
            self.assertIn("result.fedFrames =", body, function_name)
            self.assertIn("result.lastFinalsBeforeFinish =", body, function_name)

    def test_active_enhancement_keeps_speaker_vad_enabled(self) -> None:
        sdk = SDK.read_text(encoding="utf-8")
        self.assertIn("!enabled && this.targetSpeakerEnhancementEnabled", sdk)
        self.assertIn("speaker VAD cannot be disabled", sdk)

    def test_active_enhancement_uses_raw_audio_only_for_fast_partials(self) -> None:
        sdk = SDK.read_text(encoding="utf-8")
        self.assertIn("private targetSpeakerPreviewSession?: AsrSession;", sdk)
        self.assertIn("new DingqiaoTargetSpeakerPreviewCallback", sdk)
        self.assertIn("previewSession.acceptPcmBytes(audio);", sdk)
        self.assertIn("this.targetSpeakerEnhancementPipeline.append(pcm16ToFloat(audio));", sdk)
        self.assertIn("handleTargetSpeakerPreviewPartial", sdk)
        self.assertIn("result.targetSpeakerEnhancementApplied = false;", sdk)
        self.assertIn("pipeline.inputSamplesAccepted()", sdk)
        self.assertIn("target speaker enhancement input mismatch", sdk)
        self.assertIn(
            "this.targetSpeakerFastPartialEnabled = enhancementEnabled && this.partialEnabled;",
            sdk,
        )

        write_start = sdk.index("  writeAudio(sessionId: string, audio: ArrayBuffer): void {")
        write_end = sdk.index("  setSpeakerVadEnabled(enabled: boolean): void {", write_start)
        write_body = sdk[write_start:write_end]
        self.assertLess(
            write_body.index("this.targetSpeakerEnhancementPipeline.append(pcm16ToFloat(audio));"),
            write_body.index("previewSession.acceptPcmBytes(audio);"),
            "authoritative audio must be reserved before a reentrant preview callback",
        )

        preview_callback = sdk[sdk.index("class DingqiaoTargetSpeakerPreviewCallback") :]
        self.assertIn("onPartial(text: string): void", preview_callback)
        self.assertNotIn("handleFinalResult", preview_callback)
        self.assertNotIn("handleSessionStopped", preview_callback)

    def test_device_latency_probe_measures_enhanced_fast_partial_from_first_audio(self) -> None:
        source = DEVICE_STRESS.read_text(encoding="utf-8")
        start = source.index("async function runTargetSpeakerEnhancementCycle")
        end = source.index("function enableTargetSpeakerEnhancement", start)
        body = source[start:end]
        self.assertIn("params.extraParams['enablePartialResult'] = true", body)
        self.assertIn("events.audioFeedStartedAtMs = Date.now()", body)
        self.assertIn("events.partials > 0", body)
        self.assertIn("result.audioStartToFirstNonEmptyPartialMs < 0", body)
        self.assertIn("events.liveStreamsAtStart === 2", body)

    def test_public_flag_is_strict_opt_in_and_requires_speaker_vad(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ targetSpeakerEnhancementConfig }} from {CONFIG.as_uri()!r};

            assert.deepEqual(targetSpeakerEnhancementConfig({{}}, []), {{ enabled: false }});
            assert.deepEqual(
              targetSpeakerEnhancementConfig({{ enableTargetSpeakerEnhancement: 'true' }}, ['vp']),
              {{ enabled: false }}
            );
            assert.deepEqual(
              targetSpeakerEnhancementConfig({{
                enableTargetSpeakerEnhancement: true,
                enableSpeakerVad: true
              }}, ['vp']),
              {{ enabled: true }}
            );
            assert.throws(
              () => targetSpeakerEnhancementConfig({{ enableTargetSpeakerEnhancement: true }}, ['vp']),
              /enableSpeakerVad=true/
            );
            assert.throws(
              () => targetSpeakerEnhancementConfig({{
                enableTargetSpeakerEnhancement: true,
                enableSpeakerVad: true
              }}, []),
              /voiceprintIds/
            );
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
