import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PARAM_POLICY = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/BooleanParam.ts"
)
ADAPTER = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
RECOGNITION_CONFIG = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/RecognitionConfig.ets"
)


class HarmonyBooleanParamPolicyTest(unittest.TestCase):
    def run_policy(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ compatibleBooleanParam, strictBooleanParam }} from {PARAM_POLICY.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_false_representations_restore_prepack(self) -> None:
        self.run_policy(
            """
            for (const value of [false, 0, 'false', 'FALSE', '0']) {
              assert.equal(compatibleBooleanParam({ value }, 'value', true), false);
            }
            """
        )

    def test_true_representations_and_default_are_preserved(self) -> None:
        self.run_policy(
            """
            for (const value of [true, 1, -2, 'true', 'TRUE', '1']) {
              assert.equal(compatibleBooleanParam({ value }, 'value', false), true);
            }
            assert.equal(compatibleBooleanParam({}, 'value', true), true);
            assert.equal(compatibleBooleanParam({ value: {} }, 'value', true), true);
            for (const value of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
              assert.equal(compatibleBooleanParam({ value }, 'value', true), true);
            }
            """
        )

    def test_strict_policy_does_not_expand_voiceprint_flag_types(self) -> None:
        self.run_policy(
            """
            assert.equal(strictBooleanParam({ value: true }, 'value', false), true);
            for (const value of ['true', 1, {}, Number.NaN]) {
              assert.equal(strictBooleanParam({ value }, 'value', false), false);
            }
            """
        )

    def run_builder(self, body: str) -> None:
        # Execute the real ArkTS builder, Core types, and mode/provider helpers.
        # Only the Harmony platform import and bundled hotword I/O are substituted.
        core = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr"
        police = REPO_ROOT / "asr/harmony/sdk-police/src/main/ets/com/amphion/police"
        endpoint = RECOGNITION_CONFIG.with_name("EndpointRulePolicy.ts")
        models = RECOGNITION_CONFIG.with_name("DingqiaoModels.ets")
        loader = textwrap.dedent(
            """
            import { existsSync, readFileSync } from 'node:fs';
            import { stripTypeScriptTypes } from 'node:module';
            import { fileURLToPath } from 'node:url';

            const core = new URL(__CORE__);
            const police = new URL(__POLICE__);
            const moduleUrl = source => 'data:text/javascript,' + encodeURIComponent(source);
            const aliases = new Map([
              ['amphion_asr', moduleUrl(
                `export * from '${new URL('Types.ets', core)}';
                 export * from '${new URL('AsrSchedulingConfig.ts', core)}';`)],
              ['amphion_police', new URL('PoliceEngineConfig.ets', police).href],
              ['@kit.AbilityKit', moduleUrl('export const common = {};')],
            ]);

            export async function resolve(specifier, context, nextResolve) {
              if (aliases.has(specifier)) {
                return { url: aliases.get(specifier), shortCircuit: true };
              }
              if (specifier === './PoliceAssets' &&
                  context.parentURL.endsWith('/PoliceEngineConfig.ets')) {
                return { url: moduleUrl(
                  'export class PoliceAssets { static readHotwords() { return []; } }'),
                  shortCircuit: true };
              }
              try {
                return await nextResolve(specifier, context);
              } catch (error) {
                if (specifier.startsWith('./') || specifier.startsWith('../')) {
                  for (const extension of ['.ts', '.ets']) {
                    const url = new URL(specifier + extension, context.parentURL);
                    if (existsSync(fileURLToPath(url))) {
                      return { url: url.href, shortCircuit: true };
                    }
                  }
                }
                throw error;
              }
            }

            export async function load(url, context, nextLoad) {
              if (url.endsWith('.ets') || url.endsWith('.ts')) {
                return { format: 'module', shortCircuit: true,
                  source: stripTypeScriptTypes(readFileSync(new URL(url), 'utf8'),
                    { mode: 'transform', sourceUrl: url }) };
              }
              return nextLoad(url, context);
            }
            """
        ).replace("__CORE__", json.dumps(core.as_uri() + "/")).replace(
            "__POLICE__", json.dumps(police.as_uri() + "/")
        )
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ buildAsrConfig }} from {RECOGNITION_CONFIG.as_uri()!r};
            import {{ CreateEngineParams, StartParams, SpeakerDiarizationConfig }} from {models.as_uri()!r};
            import {{ AsrConfig }} from {(core / 'Types.ets').as_uri()!r};
            import {{ asrCpuProvider }} from {(core / 'AsrSchedulingConfig.ts').as_uri()!r};
            import {{ endpointRecognizerRuntimeConfigKey, endpointRecognizerConfigKey }} from {endpoint.as_uri()!r};
            const context = {{}};
            {body}
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            loader_path = Path(directory) / "recognition-config-loader.mjs"
            loader_path.write_text(loader, encoding="utf-8")
            subprocess.run(
                ["node", "--experimental-loader", loader_path.as_uri(),
                 "--input-type=module", "-e", script],
                check=True,
                cwd=REPO_ROOT,
            )

    def test_real_builder_keeps_prepare_short_and_core_defaults(self) -> None:
        self.run_builder(
            """
            assert.equal(new AsrConfig().disablePrepack, true);
            assert.equal(AsrConfig.builder().build().disablePrepack, true);
            // prepareRuntime calls this exact builder with fresh default engine params.
            const params = new CreateEngineParams();
            const prepared = buildAsrConfig(context, params);
            assert.equal(prepared.numThreads, 4);
            assert.equal(prepared.disablePrepack, true);
            assert.equal(prepared.endpointRules.rule3MinUtteranceLengthSec, 20);
            assert.equal(asrCpuProvider(prepared.disablePrepack, prepared.scheduling),
              'cpu;DisablePrepacking=1');
            assert.deepEqual(params.extraParams, {});
            const ordinaryStart = new StartParams();
            const started = buildAsrConfig(context, params, ordinaryStart);
            assert.equal(started.disablePrepack, prepared.disablePrepack);
            """
        )

    def test_real_builder_enables_prepack_for_resolved_long_modes(self) -> None:
        self.run_builder(
            """
            const cases = [
              [{ recognizerMode: 'long' }, undefined],
              [{ recognizerMode: ' LONG ' }, undefined],
              [{}, { recognizerMode: 'long' }],
              [{}, { enableContinuousRecognition: true }],
              [{ recognizerMode: 'short' }, { recognizerMode: 'long' }],
            ];
            for (const [engineExtra, sessionExtra] of cases) {
              const params = new CreateEngineParams();
              params.extraParams = engineExtra;
              const start = sessionExtra === undefined ? undefined : new StartParams();
              if (start !== undefined) start.extraParams = sessionExtra;
              const config = buildAsrConfig(context, params, start);
              assert.equal(config.disablePrepack, false, JSON.stringify([engineExtra, sessionExtra]));
              assert.equal(config.endpointRules.rule3MinUtteranceLengthSec, -1);
              assert.equal(asrCpuProvider(config.disablePrepack, config.scheduling), 'cpu');
            }
            """
        )

    def test_real_builder_uses_resolved_mode_precedence(self) -> None:
        self.run_builder(
            """
            const cases = [
              [{ recognizerMode: 'short' }, { enableContinuousRecognition: true }],
              [{ recognizerMode: 'long' }, { recognizerMode: 'short', enableContinuousRecognition: true }],
              [{}, { recognizerMode: ' SHORT ', enableContinuousRecognition: true }],
            ];
            for (const [engineExtra, sessionExtra] of cases) {
              const params = new CreateEngineParams();
              params.extraParams = engineExtra;
              const start = new StartParams();
              start.extraParams = sessionExtra;
              const config = buildAsrConfig(context, params, start);
              assert.equal(config.disablePrepack, true);
              assert.equal(config.endpointRules.rule3MinUtteranceLengthSec, 20);
            }
            """
        )

    def test_real_builder_engine_prepack_override_wins_in_both_modes(self) -> None:
        self.run_builder(
            """
            const cases = [
              [{}, undefined],
              [{ recognizerMode: 'short' }, { enableContinuousRecognition: true }],
              [{ recognizerMode: 'long' }, undefined],
              [{}, { enableContinuousRecognition: true }],
              [{}, { recognizerMode: 'long' }],
              [{ recognizerMode: 'long' }, { recognizerMode: 'short' }],
            ];
            for (const disablePrepack of [true, false]) {
              for (const [engineExtra, sessionExtra] of cases) {
                const params = new CreateEngineParams();
                params.extraParams = { ...engineExtra, disablePrepack };
                const start = sessionExtra === undefined ? undefined : new StartParams();
                // StartParams cannot override the engine's explicit prepack setting.
                if (start !== undefined) start.extraParams = {
                  ...sessionExtra, disablePrepack: !disablePrepack };
                assert.equal(buildAsrConfig(context, params, start).disablePrepack, disablePrepack);
              }
            }
            """
        )

    def test_real_builder_does_not_treat_session_prepack_as_engine_override(self) -> None:
        self.run_builder(
            """
            const params = new CreateEngineParams();
            const short = new StartParams();
            short.extraParams = { disablePrepack: false };
            assert.equal(buildAsrConfig(context, params, short).disablePrepack, true);
            const long = new StartParams();
            long.extraParams = { enableContinuousRecognition: true, disablePrepack: true };
            assert.equal(buildAsrConfig(context, params, long).disablePrepack, false);
            """
        )

    def test_existing_mode_keys_cover_prepack_transition_without_role_key(self) -> None:
        self.run_builder(
            """
            const params = new CreateEngineParams();
            const short = new StartParams();
            const long = new StartParams();
            long.extraParams = { enableContinuousRecognition: true };
            assert.notEqual(
              endpointRecognizerRuntimeConfigKey(params.extraParams, short.extraParams),
              endpointRecognizerRuntimeConfigKey(params.extraParams, long.extraParams));
            assert.notEqual(
              endpointRecognizerConfigKey(false, false, params.extraParams, short.extraParams),
              endpointRecognizerConfigKey(false, false, params.extraParams, long.extraParams));
            const withoutRole = buildAsrConfig(context, params, long);
            const existingKey = endpointRecognizerRuntimeConfigKey(params.extraParams, long.extraParams);
            long.speakerDiarization = new SpeakerDiarizationConfig();
            const withRole = buildAsrConfig(context, params, long);
            assert.equal(withoutRole.disablePrepack, false);
            assert.equal(withRole.disablePrepack, withoutRole.disablePrepack);
            assert.equal(endpointRecognizerRuntimeConfigKey(params.extraParams, long.extraParams), existingKey);
            const shortConfig = buildAsrConfig(context, params, short);
            assert.notEqual(asrCpuProvider(shortConfig.disablePrepack, shortConfig.scheduling),
              asrCpuProvider(withRole.disablePrepack, withRole.scheduling));
            """
        )

    def test_adapter_uses_compatible_policy_only_for_prepack(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8")
        config = RECOGNITION_CONFIG.read_text(encoding="utf-8")
        self.assertIn(
            "import { strictBooleanParam } from './BooleanParam';",
            adapter,
        )
        self.assertIn(
            "import { compatibleBooleanParam } from './BooleanParam';",
            config,
        )
        self.assertIn(
            "config.disablePrepack = compatibleBooleanParam(params.extraParams, 'disablePrepack', endpointRule3.mode !== 'long');",
            config,
        )
        self.assertIn(
            "const verify = strictBooleanParam(params.extraParams, 'enableVoiceprintVerification', false);",
            adapter,
        )
        self.assertIn(
            "const speakerVad = strictBooleanParam(params.extraParams, 'enableSpeakerVad', false);",
            adapter,
        )


if __name__ == "__main__":
    unittest.main()
