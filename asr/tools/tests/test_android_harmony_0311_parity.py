from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID = ROOT / "asr" / "android"
HARMONY = ROOT / "asr" / "harmony"
SHARED_MODELS = ROOT / "shared" / "models" / "asr"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AndroidHarmony0311ParityTest(unittest.TestCase):
    def test_speaker_models_are_the_same_on_both_platforms(self) -> None:
        shared_speaker = SHARED_MODELS / "dingqiao/eres2net.onnx"
        shared_segmentation = (
            SHARED_MODELS / "dingqiao/pyannote-segmentation-3.0.onnx"
        )
        shared_license = (
            SHARED_MODELS / "dingqiao/pyannote-segmentation-3.0.LICENSE"
        )
        android_build = (ANDROID / "sdk-dingqiao/build.gradle.kts").read_text(
            encoding="utf-8"
        )
        harmony_build = (
            HARMONY / "sdk-dingqiao/hvigorfile.ts"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b",
            sha256(shared_speaker),
        )
        self.assertEqual(
            "057ee564753071c0b09b5b611648b50ac188d50846bff5f01e9f7bbf1591ea25",
            sha256(shared_segmentation),
        )
        self.assertTrue(shared_license.is_file())
        for build in (android_build, harmony_build):
            self.assertIn("shared/models/asr/dingqiao", build)
            self.assertIn("eres2net.onnx", build)
            self.assertIn("pyannote-segmentation-3.0.onnx", build)
            self.assertIn("pyannote-segmentation-3.0.LICENSE", build)

    def test_shared_police_assets_are_byte_identical(self) -> None:
        android_root = ANDROID / "sdk-police/src/main/assets"
        harmony_root = (
            HARMONY
            / "sdk-police/src/main/resources/rawfile/amphion-police"
        )
        android_files = {
            path.relative_to(android_root)
            for path in android_root.rglob("*")
            if path.is_file()
        }
        harmony_shared_files = {
            path.relative_to(harmony_root)
            for path in harmony_root.rglob("*")
            if path.is_file()
            and path.name not in {"manifest.json", "hotwords.json", "lac_encoder.onnx"}
        }
        self.assertEqual(harmony_shared_files, android_files)
        for relative in sorted(android_files):
            self.assertEqual(
                sha256(harmony_root / relative),
                sha256(android_root / relative),
                str(relative),
            )

        shared_lac = SHARED_MODELS / "police/lac/v1/lac_encoder.onnx"
        android_police_build = (ANDROID / "sdk-police/build.gradle.kts").read_text(
            encoding="utf-8"
        )
        harmony_police_build = (
            HARMONY / "sdk-police/hvigorfile.ts"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            "826085fff327d0c76c0dd55400629ce0ed192a6519ecd9841ed6fdedb4cb5aec",
            sha256(shared_lac),
        )
        for build in (android_police_build, harmony_police_build):
            self.assertIn("shared/models/asr/police/lac/v1", build)
            self.assertIn("lac_encoder.onnx", build)

    def test_android_keeps_release_identity_frozen_until_device_gate(self) -> None:
        properties = (ANDROID / "gradle.properties").read_text(encoding="utf-8")
        version = re.search(
            r"^AMPHION_RUNTIME_VERSION=(.+)$", properties, flags=re.MULTILINE
        )
        self.assertIsNotNone(version)
        self.assertNotEqual("0.3.11", version.group(1))

        parity = (ANDROID / "docs/HARMONY_0.3.11_PARITY.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Diagnostics SDK", parity)
        self.assertIn("Speaker Diarization", parity)
        self.assertIn("真机发布门禁", parity)

    def test_android_exposes_offline_diarization_and_lac_person_normalization(self) -> None:
        models = (ANDROID / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoModels.kt").read_text()
        engine = (ANDROID / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoRecognitionEngine.kt").read_text()
        native = (ANDROID / "sdk-dingqiao/src/main/cpp/speaker_turn_segmenter_jni.cpp").read_text()
        police = (ANDROID / "sdk-police/src/main/java/com/amphion/police/PoliceEnhancePipeline.kt").read_text()
        self.assertIn("data class SpeakerDiarizationConfig", models)
        self.assertIn("onSpeakerDiarizationResult", models)
        self.assertIn("requestSpeakerDiarizationFinishLocked", engine)
        self.assertIn("kMasks{0, 1, 2, 4, 3, 5, 6}", native)
        self.assertIn("configurePersonNames", police)

    def test_diagnostics_are_compile_time_isolated_and_export_schema_two(self) -> None:
        build = (ANDROID / "sdk-dingqiao/build.gradle.kts").read_text()
        module = (ANDROID / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/DiagnosticsModule.kt").read_text()
        self.assertIn('create("diagnostics")', build)
        self.assertIn('"schemaVersion" to 2', module)
        self.assertIn("recoverCrashJournalsLocked", module)
        self.assertIn("resource-samples.csv", module)

    def test_android_exposes_runtime_log_level_without_changing_session_policy(self) -> None:
        adapter = (
            ANDROID
            / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/SpeechRecognizeSdk.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("fun setLogLevel(logLevel: AmphionLogLevel)", adapter)
        self.assertGreaterEqual(adapter.count("logLevel = runtimeLogLevel"), 2)
        self.assertNotIn("runtimeLogLevel", adapter.split("fun setLogLevel", 1)[0].split("private var runtimeLogLevel", 1)[0])

    def test_public_work_path_and_recognition_mode_aliases_match_harmony(self) -> None:
        adapter = (
            ANDROID
            / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/SpeechRecognizeSdk.kt"
        ).read_text(encoding="utf-8")
        constants = (
            ANDROID
            / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoErrorCode.kt"
        ).read_text(encoding="utf-8")
        models = (
            ANDROID
            / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoModels.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("fun getWorkPath(): String", adapter)
        self.assertIn("const val SINGLE = RECORD", constants)
        self.assertIn("const val CONTINUOUS = STREAM", constants)
        self.assertIn("val errorCode: Int = 0", models)
        self.assertIn('val errorMessage: String = ""', models)

    def test_public_device_provider_frame_constant_and_output_defaults_match_harmony(self) -> None:
        adapter = (
            ANDROID
            / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/SpeechRecognizeSdk.kt"
        ).read_text(encoding="utf-8")
        constants = (
            ANDROID
            / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoErrorCode.kt"
        ).read_text(encoding="utf-8")
        models = (
            ANDROID
            / "sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoModels.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("fun interface LicenseDeviceIdProvider", adapter)
        self.assertIn("fun init(context: Context, deviceIdProvider: LicenseDeviceIdProvider?)", adapter)
        self.assertIn("DINGQIAO_AUDIO_FRAME_BYTES_20MS = 640", constants)
        self.assertIn('val utteranceId: String = ""', models)
        self.assertIn("val speakerIndex: Int = -1", models)


if __name__ == "__main__":
    unittest.main()
