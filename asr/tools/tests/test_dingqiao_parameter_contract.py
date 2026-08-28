from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from asr.tools.dingqiao_parameter_contract import (
    CONTRACT_PATH,
    ParameterContractError,
    load_contract,
    validate_parameter_document,
)


ROOT = Path(__file__).resolve().parents[3]
ANDROID_CONFIG = (
    ROOT
    / "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoEngineConfig.kt"
)
ANDROID_MODELS = (
    ROOT
    / "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoModels.kt"
)
HARMONY_ENGINE = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
HARMONY_AUDIO_INFO = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/AudioInfoValidation.ts"
)
HARMONY_ENDPOINT_POLICY = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/EndpointRulePolicy.ts"
)
HARMONY_AUDIO_LIMIT = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SessionAudioLimit.ts"
)
HARMONY_TARGET_ENHANCEMENT = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/TargetSpeakerEnhancementConfig.ts"
)
HARMONY_MODELS = (
    ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DingqiaoModels.ets"
)
ANDROID_DOC = ROOT / "asr/android/docs/customer/语音识别SDK接口.md"
HARMONY_DOC = ROOT / "delivery/harmony-dingqiao/docs/语音识别SDK接口.md"


def _constant(source: str, name: str) -> float:
    match = re.search(rf"{name}\s*=\s*([0-9.]+)", source)
    if match is None:
        raise AssertionError(f"missing constant {name}")
    return float(match.group(1))


class DingqiaoParameterContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract()
        self.android = ANDROID_CONFIG.read_text(encoding="utf-8")
        self.harmony = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                HARMONY_ENGINE,
                HARMONY_AUDIO_INFO,
                HARMONY_ENDPOINT_POLICY,
                HARMONY_AUDIO_LIMIT,
                HARMONY_TARGET_ENHANCEMENT,
            )
        )

    def test_contract_is_valid_json_and_has_unique_parameter_keys(self) -> None:
        payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(1, payload["schema_version"])
        for section in ("create_engine", "start"):
            keys = list(payload[section]["extra_params"])
            self.assertEqual(len(keys), len(set(keys)), section)

    def test_common_extra_parameter_names_exist_on_both_platforms(self) -> None:
        create_keys = self.contract["create_engine"]["extra_params"]
        start_keys = self.contract["start"]["extra_params"]
        no_op_keys = {"locate", "sessionGeneralLexicon"}
        for key in sorted({*create_keys, *start_keys} - no_op_keys):
            with self.subTest(key=key):
                self.assertTrue(f'"{key}"' in self.android, key)
                self.assertTrue(f"'{key}'" in self.harmony, key)

    def test_public_parameter_objects_and_result_fields_exist_on_both_platforms(self) -> None:
        android_models = ANDROID_MODELS.read_text(encoding="utf-8")
        harmony_models = HARMONY_MODELS.read_text(encoding="utf-8")
        for key in (
            *self.contract["create_engine"]["fields"],
            *self.contract["start"]["fields"],
            *self.contract["speaker_diarization"]["fields"],
            *self.contract["voiceprint_register"]["fields"],
            *self.contract["result_contract"].values(),
        ):
            with self.subTest(key=key):
                self.assertRegex(android_models, rf"\b{re.escape(key)}\b")
                self.assertRegex(harmony_models, rf"\b{re.escape(key)}\b")

    def test_voiceprint_registration_failure_contract_is_explicit_on_both_platforms(self) -> None:
        voiceprint = self.contract["voiceprint_register"]
        self.assertEqual("return_status_and_message", voiceprint["result"]["failure"])
        android_sdk = (
            ROOT
            / "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/SpeechRecognizeSdk.kt"
        ).read_text(encoding="utf-8")
        self.assertTrue("voiceprintRegistrationFailure" in android_sdk)
        self.assertTrue("result.status = DingqiaoErrorCode.VOICEPRINT_SAMPLE_COUNT" in self.harmony)

    def test_voiceprint_registration_validates_audio_info_before_samples(self) -> None:
        android_sdk = (
            ROOT
            / "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/SpeechRecognizeSdk.kt"
        ).read_text(encoding="utf-8")
        android_method = android_sdk[android_sdk.index("fun registerVoiceprint("):]
        harmony_method = self.harmony[self.harmony.index("static registerVoiceprint("):]
        for source, validation, sample_check in (
            (android_method, "params.audioInfo.validate()", "params.samplePaths.size"),
            (harmony_method, "validateAudioInfo(params.audioInfo)", "params.samplePaths.length"),
        ):
            with self.subTest(validation=validation):
                self.assertIn(validation, source)
                self.assertLess(source.index(validation), source.index(sample_check))
                prefix = source[:source.index(sample_check)]
                self.assertIn("VOICEPRINT_REGISTER_FAILED", prefix)
        self.assertIn(
            'require(sampleRate == 16000) { "sampleRate must be 16000" }',
            ANDROID_MODELS.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "if (audioInfo.sampleRate !== 16000) return 'sampleRate must be 16000'",
            self.harmony,
        )

    def test_integer_millisecond_parameters_declare_rounding(self) -> None:
        extra = self.contract["start"]["extra_params"]
        for key in (
            "vadBegin",
            "vadEnd",
            "maxAudioDuration",
            "speakerVadWindowMs",
            "speakerVadHopMs",
        ):
            with self.subTest(key=key):
                self.assertEqual("nearest_integer", extra[key].get("rounding"))

    def test_speaker_vad_defaults_match_contract_on_both_platforms(self) -> None:
        extra = self.contract["start"]["extra_params"]
        android_names = {
            "speakerVadThreshold": "DEFAULT_SPEAKER_VAD_THRESHOLD",
            "speakerVadWindowMs": "DEFAULT_SPEAKER_VAD_WINDOW_MS",
            "speakerVadHopMs": "DEFAULT_SPEAKER_VAD_HOP_MS",
            "speakerVadConsecutiveBelow": "DEFAULT_SPEAKER_VAD_CONSECUTIVE_BELOW",
        }
        for key, constant in android_names.items():
            with self.subTest(platform="android", key=key):
                self.assertEqual(float(extra[key]["default"]), _constant(self.android, constant))

        harmony_patterns = {
            "speakerVadThreshold": r"speakerVadThreshold',\s*([0-9.]+)",
            "speakerVadWindowMs": r"speakerVadWindowMs',\s*([0-9.]+)",
            "speakerVadHopMs": r"speakerVadHopMs',\s*([0-9.]+)",
            "speakerVadConsecutiveBelow": r"speakerVadConsecutiveBelow',\s*([0-9.]+)",
        }
        for key, pattern in harmony_patterns.items():
            with self.subTest(platform="harmony", key=key):
                match = re.search(pattern, self.harmony)
                self.assertIsNotNone(match)
                self.assertEqual(float(extra[key]["default"]), float(match.group(1)))

    def test_boolean_and_mode_priority_semantics_match(self) -> None:
        self.assertTrue(
            'startParams.extraParams["enableSpeakerVad"] as? Boolean ?: false'
            in self.android,
        )
        self.assertTrue(
            "strictBooleanParam(params.extraParams, 'enableSpeakerVad', false)"
            in self.harmony,
        )
        for source in (self.android, self.harmony):
            self.assertTrue("enableContinuousRecognition" in source)
            self.assertTrue("recognizerMode" in source)
            self.assertTrue("short" in source)
            self.assertTrue("long" in source)
        self.assertLess(
            self.android.index('startParams?.extraParams?.get("recognizerMode")'),
            self.android.index('params.extraParams["recognizerMode"]'),
        )
        self.assertTrue(
            "sessionExtraParams['recognizerMode'] ?? engineExtraParams['recognizerMode']"
            in HARMONY_ENDPOINT_POLICY.read_text(encoding="utf-8"),
        )

    def test_online_mode_is_rejected_consistently(self) -> None:
        self.assertIn("params.online == DingqiaoOnlineMode.OFFLINE", self.android)
        self.assertIn("params.online !== DingqiaoOnlineMode.OFFLINE", self.harmony)

    def test_license_binding_error_mapping_matches_public_contract(self) -> None:
        expected = self.contract["error_contract"][
            "license_application_certificate_or_device_mismatch"
        ]
        self.assertEqual(1002200033, expected["code"])
        android_sdk = (
            ROOT
            / "asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/SpeechRecognizeSdk.kt"
        ).read_text(encoding="utf-8")
        self.assertTrue(
            "AsrErrorCode.LICENSE_APP_MISMATCH,\n        "
            "AsrErrorCode.LICENSE_CERT_MISMATCH,\n        "
            "-> DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH" in android_sdk
        )
        self.assertTrue(
            "AsrErrorCode.LICENSE_APP_MISMATCH ||\n    "
            "asrCode === AsrErrorCode.LICENSE_CERT_MISMATCH ||" in self.harmony
        )
        for source in (android_sdk, self.harmony):
            for name in (
                "LICENSE_MALFORMED",
                "LICENSE_SIGNATURE_INVALID",
                "LICENSE_SDK_MAJOR_MISMATCH",
                "LICENSE_FEATURE_MISSING",
                "LICENSE_EXPIRED",
                "LICENSE_MAINTENANCE_EXPIRED",
            ):
                self.assertTrue(name in source, name)

    def test_platform_extension_is_not_misrepresented_as_common(self) -> None:
        extension = self.contract["platform_extensions"]["harmony"]
        self.assertIn("enableTargetSpeakerEnhancement", extension)
        self.assertFalse(extension["enableTargetSpeakerEnhancement"]["common_customer_configuration"])
        self.assertIn("'enableTargetSpeakerEnhancement'", self.harmony)
        self.assertNotIn('"enableTargetSpeakerEnhancement"', self.android)

    def test_android_and_harmony_customer_documents_match_common_contract(self) -> None:
        validate_parameter_document(ANDROID_DOC.read_text(encoding="utf-8"), self.contract)
        validate_parameter_document(HARMONY_DOC.read_text(encoding="utf-8"), self.contract)

    def test_stale_speaker_vad_document_is_rejected(self) -> None:
        stale = ANDROID_DOC.read_text(encoding="utf-8").replace(
            "| `speakerVadThreshold` | `Number/String` | `0.35` |",
            "| `speakerVadThreshold` | `Number/String` | `0.40` |",
        )
        with self.assertRaisesRegex(ParameterContractError, "speakerVadThreshold"):
            validate_parameter_document(stale, self.contract)


if __name__ == "__main__":
    unittest.main()
