import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_PAGE = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/"
    "Index.ets"
)
DEMO_PREFS = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/"
    "DemoPrefs.ets"
)
PIPELINE_CONFIG = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/"
    "SpeakerPipelineConfig.ts"
)
SESSION_DEBUG = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/"
    "DemoSessionDebug.ts"
)


class HarmonyDemoSpeakerPipelineTest(unittest.TestCase):
    def run_node(self, script: str) -> None:
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_pipeline_config_is_safe_by_default_and_enforces_dependencies(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{
              applySpeakerPipelineConfig,
              captureSpeakerPipelineConfig,
            }} from {PIPELINE_CONFIG.as_uri()!r};

            const defaults = captureSpeakerPipelineConfig('vp-1', false, false, false);
            assert.equal(defaults.speakerVad, false);
            assert.equal(defaults.targetSpeakerEnhancement, false);
            const defaultExtra = {{}};
            applySpeakerPipelineConfig(defaultExtra, defaults);
            assert.equal('enableSpeakerVad' in defaultExtra, false);
            assert.equal('enableTargetSpeakerEnhancement' in defaultExtra, false);

            const enhanced = captureSpeakerPipelineConfig('vp-1', true, false, true);
            assert.equal(enhanced.voiceprintVerify, true);
            assert.equal(enhanced.speakerVad, true);
            assert.equal(enhanced.targetSpeakerEnhancement, true);
            const enhancedExtra = {{}};
            applySpeakerPipelineConfig(enhancedExtra, enhanced);
            assert.equal(enhancedExtra.enableSpeakerVad, true);
            assert.equal(enhancedExtra.enableTargetSpeakerEnhancement, true);
            assert.deepEqual(enhancedExtra.voiceprintIds, ['vp-1']);

            const missingVoiceprint = captureSpeakerPipelineConfig('', true, true, true);
            assert.equal(missingVoiceprint.voiceprintVerify, false);
            assert.equal(missingVoiceprint.speakerVad, false);
            assert.equal(missingVoiceprint.targetSpeakerEnhancement, false);
            """
        )
        self.run_node(script)

    def test_session_debug_keeps_counters_and_bounds_trace(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ DemoSessionDebug }} from {SESSION_DEBUG.as_uri()!r};

            const debug = new DemoSessionDebug(1000, 3);
            debug.configure('vp-1', true, true, true, false, 1001);
            debug.record('startListening', 'session-1', 'cold-load', 1010);
            debug.addAudioFrame(640, 1020);
            debug.addAudioFrame(640, 1040);
            debug.addResult('session-1', '测试', true, false, 0.82, true, 1050);
            debug.record('finish', 'session-1', 'user', 1060);

            const snapshot = debug.snapshot(1070);
            assert.equal(snapshot.audioFrames, 2);
            assert.equal(snapshot.audioBytes, 1280);
            assert.equal(snapshot.audioDurationMs, 40);
            assert.equal(snapshot.finalResults, 1);
            assert.equal(snapshot.lastResults, 0);
            assert.equal(snapshot.enhancedResults, 1);
            assert.equal(snapshot.lastSpeakerSimilarity, 0.82);
            assert.equal(snapshot.trace.length, 3);
            assert.equal(snapshot.droppedTraceEntries, 2);
            assert.match(debug.summary(1070), /增强=开/);
            assert.match(debug.traceText(), /finish/);

            const longPartial = '长'.repeat(500);
            debug.addResult('session-1', longPartial, false, false, undefined, true, 1080);
            assert.equal(debug.traceText().includes(longPartial), false);
            """
        )
        self.run_node(script)

    def test_demo_exposes_switch_and_exports_debug_snapshot(self) -> None:
        demo = DEMO_PAGE.read_text(encoding="utf-8")
        prefs = DEMO_PREFS.read_text(encoding="utf-8")
        self.assertIn("Text('目标说话人增强')", demo)
        self.assertIn("enableTargetSpeakerEnhancement", demo)
        self.assertIn("targetSpeakerEnhancementApplied", demo)
        self.assertIn("meta['sessionDebug']", demo)
        self.assertIn("if (!this.startRecognitionSession())", demo)
        self.assertIn("return engine.isBusy() && this.sessionId === sid", demo)
        self.assertIn("stage=config_snapshot", demo)
        self.assertIn("stage=audio_progress", demo)
        self.assertIn("getTargetSpeakerEnhancementEnabled", prefs)
        self.assertIn("setTargetSpeakerEnhancementEnabled", prefs)


if __name__ == "__main__":
    unittest.main()
