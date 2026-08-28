from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from asr.tools.dingqiao_parameter_contract import canonical_contract_bytes


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).parents[1] / "delivery/validate_android_sdk_only_delivery.py"
SPEC = importlib.util.spec_from_file_location("validate_android_sdk_only_delivery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AndroidSdkOnlyDeliveryTest(unittest.TestCase):
    version = "0.3.3"

    def _aar(
        self,
        *,
        preview: bool = False,
        yue: bool = False,
        embedded_license: bool = False,
        include_plate: bool = True,
        include_agc: bool = True,
        internal_meta: bool = False,
        local_path: bool = False,
    ) -> bytes:
        output = io.BytesIO()
        names = [
            "assets/amphion-models/zh-en/v1/model.ort",
            "assets/amphion-models/punct-zhen/v1/model.ort",
            "assets/amphion-models/itn-zh/v1/tagger.fst",
            "assets/amphion-models/vad/v1/vad.onnx",
            "assets/amphion-dingqiao/eres2net.onnx",
            "assets/amphion-dingqiao/pyannote-segmentation-3.0.onnx",
            "assets/lac/v1/lac_encoder.onnx",
            "assets/lac/v1/lac_crf_transitions.npy",
            "jni/arm64-v8a/libamphion_diarization_jni.so",
            "jni/arm64-v8a/libamphion_police_jni.so",
            "assets/police_terms/terms.fst",
            "assets/police_station/stations.fst",
        ]
        if include_agc:
            names.append("jni/arm64-v8a/libamphion_audio_processing.so")
        if include_plate:
            names.extend(
                [
                    "assets/plate/plate_homophone.fst",
                    "assets/plate/plate_homophones.csv",
                    "assets/plate/plate_readings_v2.csv",
                    "assets/plate/plate_spec_ga36.tsv",
                ]
            )
        if yue:
            names.append("assets/amphion-models/yue-en/v1/model.ort")
        if embedded_license:
            names.append("assets/amphion-license.lic")
        with zipfile.ZipFile(output, "w") as archive:
            for name in names:
                archive.writestr(name, b"payload")
            archive.writestr(
                "META-INF/amphion-dingqiao-build.properties",
                "amphion.delivery.status="
                + ("preview-non-canonical" if preview else "formal")
                + "\n",
            )
            if internal_meta:
                archive.writestr(
                    "assets/plate/plate_homophone_meta.json",
                    b'{"source_csv":"/Users/example/internal.csv"}',
                )
            if local_path:
                archive.writestr(
                    "assets/police_terms/build_notes.txt",
                    b"source=/home/example/internal.csv",
                )
        return output.getvalue()

    def _write_zip(
        self,
        path: Path,
        *,
        include_demo: bool = False,
        yue: bool = False,
        embedded_license: bool = False,
        include_plate: bool = True,
        include_agc: bool = True,
        internal_meta: bool = False,
        local_path: bool = False,
        tamper_checksum: bool = False,
        stale_parameter_contract: bool = False,
        stale_parameter_document: bool = False,
        preview: bool = False,
        missing_status: bool = False,
    ) -> None:
        suffix = "-PREVIEW-NON-CANONICAL" if preview else ""
        root = f"amphion-dingqiao-asr-sdk-v{self.version}-20260730{suffix}"
        status = "PREVIEW / NON-CANONICAL" if preview else "FORMAL"
        files = {
            "README.txt": (
                f"交付状态：{status}\n"
                "SDK-only；警务文本增强默认开启，可按会话关闭；不包含粤英模型；"
                "不包含 Demo APK 或源码；不包含授权文件。\n"
            ).encode(),
            "VERSION.txt": (
                f"delivery_version={self.version}\n"
                f"sdk_version={self.version}\n"
                + ("" if missing_status else f"delivery_status={status}\n")
                + "platform=android\nlanguage=zh-en\nsdk_only=true\n"
                "contains_demo=false\ncontains_tts=false\ncontains_license=false\n"
            ).encode(),
            f"aar/dingqiao-asr-v{self.version}{suffix}.aar": self._aar(
                preview=preview,
                yue=yue,
                embedded_license=embedded_license,
                include_plate=include_plate,
                include_agc=include_agc,
                internal_meta=internal_meta,
                local_path=local_path,
            ),
        }
        for document in MODULE.REQUIRED_DOCS:
            files[document] = b"document"
        contract = canonical_contract_bytes()
        if stale_parameter_contract:
            contract = contract.replace(b'"default": 0.35', b'"default": 0.40', 1)
        files["docs/DINGQIAO_ASR_PARAMETER_CONTRACT.json"] = contract
        parameter_doc = (
            ROOT / "asr/android/docs/customer/语音识别SDK接口.md"
        ).read_bytes()
        if stale_parameter_document:
            parameter_doc = parameter_doc.replace(
                b"| `speakerVadThreshold` | `Number/String` | `0.35` |",
                b"| `speakerVadThreshold` | `Number/String` | `0.40` |",
            )
        files["docs/语音识别SDK接口.md"] = parameter_doc
        if include_demo:
            files["demo/demo.apk"] = b"apk"
        checksums = []
        for relative, payload in sorted(files.items()):
            digest = hashlib.sha256(payload).hexdigest()
            if tamper_checksum and relative == "README.txt":
                digest = "0" * 64
            checksums.append(f"{digest}  ./{relative}\n")
        files["CHECKSUMS.txt"] = "".join(checksums).encode()
        with zipfile.ZipFile(path, "w") as archive:
            for relative, payload in files.items():
                archive.writestr(f"{root}/{relative}", payload)

    def _delivery_path(self, directory: str, *, preview: bool = False) -> Path:
        suffix = "-PREVIEW-NON-CANONICAL" if preview else ""
        return Path(directory) / (
            f"amphion-dingqiao-asr-sdk-v{self.version}-20260730{suffix}.zip"
        )

    def test_accepts_exact_zh_en_sdk_only_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory)
            self._write_zip(path)
            MODULE.validate_delivery(path, self.version)

    def test_accepts_explicit_preview_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory, preview=True)
            self._write_zip(path, preview=True)
            MODULE.validate_delivery(path, self.version, preview=True)

    def test_rejects_unmarked_or_misclassified_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory, preview=True)
            self._write_zip(path, preview=True, missing_status=True)
            with self.assertRaisesRegex(
                MODULE.DeliveryValidationError, "delivery_status"
            ):
                MODULE.validate_delivery(path, self.version, preview=True)

        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory, preview=True)
            self._write_zip(path, preview=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "formal identity"):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_demo_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory)
            self._write_zip(path, include_demo=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "unexpected|forbidden"):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_yue_or_embedded_license(self) -> None:
        for kwargs in ({"yue": True}, {"embedded_license": True}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                path = self._delivery_path(directory)
                self._write_zip(path, **kwargs)
                with self.assertRaisesRegex(MODULE.DeliveryValidationError, "forbidden AAR"):
                    MODULE.validate_delivery(path, self.version)

    def test_rejects_missing_plate_enhancement_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory)
            self._write_zip(path, include_plate=False)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "plate_"):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_missing_agc_native_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory)
            self._write_zip(path, include_agc=False)
            with self.assertRaisesRegex(
                MODULE.DeliveryValidationError, "libamphion_audio_processing"
            ):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_internal_generator_metadata_and_local_paths(self) -> None:
        for kwargs, message in (
            ({"internal_meta": True}, "forbidden AAR"),
            ({"local_path": True}, "local build path"),
        ):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                path = self._delivery_path(directory)
                self._write_zip(path, **kwargs)
                with self.assertRaisesRegex(MODULE.DeliveryValidationError, message):
                    MODULE.validate_delivery(path, self.version)

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory)
            self._write_zip(path, tamper_checksum=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "checksum mismatch"):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_stale_parameter_contract_or_document(self) -> None:
        for kwargs, message in (
            ({"stale_parameter_contract": True}, "parameter contract"),
            ({"stale_parameter_document": True}, "speakerVadThreshold"),
        ):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                path = self._delivery_path(directory)
                self._write_zip(path, **kwargs)
                with self.assertRaisesRegex(
                    (MODULE.DeliveryValidationError, ValueError), message
                ):
                    MODULE.validate_delivery(path, self.version)

    def test_rejects_oversized_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._delivery_path(directory)
            self._write_zip(path)
            old = MODULE.MAX_SDK_ONLY_ZIP_BYTES
            MODULE.MAX_SDK_ONLY_ZIP_BYTES = 1
            try:
                with self.assertRaisesRegex(MODULE.DeliveryValidationError, "exceeds"):
                    MODULE.validate_delivery(path, self.version)
            finally:
                MODULE.MAX_SDK_ONLY_ZIP_BYTES = old


if __name__ == "__main__":
    unittest.main()
