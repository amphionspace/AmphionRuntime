import re
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
PREPARATION_STATE = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RuntimePreparationState.ts"
)
DEMO_PAGE = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets"
)
BUILD_INSTALL_SMOKE = REPO_ROOT / (
    "delivery/harmony-dingqiao/delivery/build_install_smoke.sh"
)
POOL_POLICY = REPO_ROOT / (
    "asr/harmony/sdk/src/main/ets/com/amphion/asr/RecognizerPoolPolicy.ts"
)


def method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : index]
    raise AssertionError(f"unterminated method: {signature}")


class HarmonyPrepareRuntimeModelLoadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = ADAPTER.read_text(encoding="utf-8")
        cls.runtime_source = RUNTIME.read_text(encoding="utf-8")
        cls.prepare = method_body(
            cls.source, "static prepareRuntime(callback: PrepareRuntimeCallback): void"
        )
        cls.unload_model = method_body(cls.source, "static unloadModel(): void")

    def run_state(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ RuntimePreparationState }} from {PREPARATION_STATE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_prepare_runtime_preloads_android_aligned_default_model(self) -> None:
        self.assertIn("AmphionRuntime.preloadAsync", self.prepare)
        self.assertRegex(
            self.prepare,
            re.compile(r"\[\s*AsrLanguage\.ZH_EN\s*\]"),
        )
        self.assertIn(
            "defaultConfig = buildAsrConfig(context, new CreateEngineParams())",
            self.prepare,
        )

        init_index = self.prepare.index("AmphionRuntime.init")
        preload_index = self.prepare.index("AmphionRuntime.preloadAsync")
        ready_index = self.prepare.rindex("callback.onReady()")
        self.assertLess(init_index, preload_index)
        self.assertLess(preload_index, ready_index)

    def test_prepare_runtime_does_not_preload_optional_voiceprint_model(self) -> None:
        self.assertNotIn("getOrCreateSpeakerExtractor", self.prepare)
        self.assertNotIn("preloadVoiceprintModel", self.prepare)
        self.assertNotIn("AsrLanguage.YUE_EN", self.prepare)

    def test_runtime_ready_does_not_bypass_default_model_check(self) -> None:
        self.assertIn(
            "AmphionRuntime.isModelPrepared(AsrLanguage.ZH_EN, defaultConfig)",
            self.prepare,
        )
        is_model_prepared = method_body(
            self.runtime_source,
            "static isModelPrepared(language: AsrLanguage, config?: AsrConfig): boolean",
        )
        self.assertIn("AmphionRuntime.asrPool.get(language)", is_model_prepared)
        self.assertIn("AmphionRuntime.poolConfigKey.get(language)", is_model_prepared)
        self.assertIn("AmphionRuntime.recognizerConfigKey(effectiveConfig)", is_model_prepared)

    def test_incompatible_engine_config_preserves_the_prepared_pool(self) -> None:
        self.run_state(
            f"""
            const {{ RecognizerPoolPolicy }} = await import({POOL_POLICY.as_uri()!r});
            const DEFAULT = 'default';
            const CUSTOM = 'custom-hotwords';
            assert.equal(RecognizerPoolPolicy.decide(undefined, DEFAULT),
              RecognizerPoolPolicy.PUBLISH);
            assert.equal(RecognizerPoolPolicy.decide(DEFAULT, CUSTOM),
              RecognizerPoolPolicy.DEDICATED);
            assert.equal(RecognizerPoolPolicy.decide(DEFAULT, DEFAULT),
              RecognizerPoolPolicy.REUSE);
            """
        )
        create = method_body(
            self.runtime_source,
            "static create(context: Context, language: AsrLanguage, config?: AsrConfig): AsrEngine",
        )
        self.assertRegex(
            create,
            re.compile(
                r"if \(poolAction === RecognizerPoolPolicy\.PUBLISH\) \{[\s\S]*?"
                r"AmphionRuntime\.asrPool\.set\(language, recognizer\)"
            ),
        )

        timed_async_load = method_body(
            self.runtime_source,
            "private static async timedRecognizerLoadAsync(",
        )
        self.assertIn("poolAction === RecognizerPoolPolicy.DEDICATED", timed_async_load)
        self.assertIn("createRecognizerAsync", timed_async_load)
        self.assertIn("true", timed_async_load)

        engine_close = method_body(self.runtime_source, "close(): void")
        self.assertIn("closeOwnedRecognizerWhenIdle", engine_close)
        self.assertIn("onStreamReleased", self.runtime_source)

    def test_cancelled_async_recognizer_load_closes_the_unpublished_model(self) -> None:
        create_recognizer_async = method_body(
            self.runtime_source,
            "private static async createRecognizerAsync(",
        )
        close_index = create_recognizer_async.index("recognizer.close()")
        failure_index = create_recognizer_async.index("runtime released during recognizer load")
        self.assertLess(close_index, failure_index)

        punctuation_load = method_body(
            self.runtime_source,
            "private static async getOrCreatePunctuationAsync(",
        )
        close_index = punctuation_load.index("punctuation.close()")
        failure_index = punctuation_load.index("runtime released during punctuation load")
        self.assertLess(close_index, failure_index)

    def test_unload_model_invalidates_inflight_and_completed_prepare(self) -> None:
        self.run_state(
            """
            const state = new RuntimePreparationState();
            const firstSnapshot = state.snapshot();
            const firstTask = Promise.resolve();
            state.publishTask(firstTask);
            assert.equal(state.activeTask(), firstTask);

            state.invalidateModel();
            assert.equal(state.activeTask(), undefined);
            assert.equal(state.isRuntimeCurrent(firstSnapshot), true);
            assert.equal(state.isModelCurrent(firstSnapshot), false);
            assert.equal(state.markPrepared(firstSnapshot), false);
            assert.equal(state.isDefaultModelPrepared(), false);

            const secondSnapshot = state.snapshot();
            const secondTask = Promise.resolve();
            state.publishTask(secondTask);
            assert.equal(state.markPrepared(secondSnapshot), true);
            state.clearTask(secondTask);
            assert.equal(state.activeTask(), undefined);
            assert.equal(state.isDefaultModelPrepared(), true);
            """
        )
        self.assertIn("SpeechRecognizeSdk.runtimePreparation.invalidateModel()", self.unload_model)
        self.assertIn("prepareRuntime cancelled by unloadModel", self.prepare)

    def test_invalidation_before_preload_stops_the_old_task(self) -> None:
        model_check = self.prepare.index(
            "SpeechRecognizeSdk.runtimePreparation.isModelCurrent(snapshot)"
        )
        preload = self.prepare.index("AmphionRuntime.preloadAsync")
        self.assertLess(model_check, preload)

    def test_runtime_invalidation_rejects_both_old_generations(self) -> None:
        self.run_state(
            """
            const state = new RuntimePreparationState();
            const snapshot = state.snapshot();
            state.markPrepared(snapshot);
            state.publishTask(Promise.resolve());
            state.invalidateRuntime();
            assert.equal(state.isRuntimeCurrent(snapshot), false);
            assert.equal(state.isModelCurrent(snapshot), false);
            assert.equal(state.isDefaultModelPrepared(), false);
            assert.equal(state.activeTask(), undefined);
            """
        )

    def test_current_prepare_failure_cleans_up_partial_runtime(self) -> None:
        self.assertIn("await AmphionRuntime.releaseAsync()", self.prepare)
        self.assertIn("Runtime cleanup failed", self.prepare)

    def test_demo_reports_default_model_ready_after_prepare_runtime(self) -> None:
        demo_source = DEMO_PAGE.read_text(encoding="utf-8")
        self.assertNotIn("运行时就绪（未加载模型）", demo_source)
        self.assertIn("默认中英模型已就绪", demo_source)

        smoke_source = BUILD_INSTALL_SMOKE.read_text(encoding="utf-8")
        self.assertIn('"默认中英模型已就绪" in text', smoke_source)
        self.assertNotIn('or "运行时就绪" in text', smoke_source)
        self.assertNotIn('or "引擎就绪" in text', smoke_source)


if __name__ == "__main__":
    unittest.main()
