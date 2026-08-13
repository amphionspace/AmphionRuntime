from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile


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
    ) -> None:
        root = f"amphion-dingqiao-asr-sdk-v{self.version}-20260730"
        files = {
            "README.txt": (
                "SDK-only；警务文本增强默认开启，可按会话关闭；不包含粤英模型；"
                "不包含 Demo APK 或源码；不包含授权文件。\n"
            ).encode(),
            "VERSION.txt": (
                f"delivery_version={self.version}\n"
                f"sdk_version={self.version}\n"
                "platform=android\nlanguage=zh-en\nsdk_only=true\n"
                "contains_demo=false\ncontains_tts=false\ncontains_license=false\n"
            ).encode(),
            f"aar/dingqiao-asr-v{self.version}.aar": self._aar(
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

    def test_accepts_exact_zh_en_sdk_only_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.zip"
            self._write_zip(path)
            MODULE.validate_delivery(path, self.version)

    def test_rejects_demo_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.zip"
            self._write_zip(path, include_demo=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "unexpected|forbidden"):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_yue_or_embedded_license(self) -> None:
        for kwargs in ({"yue": True}, {"embedded_license": True}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "delivery.zip"
                self._write_zip(path, **kwargs)
                with self.assertRaisesRegex(MODULE.DeliveryValidationError, "forbidden AAR"):
                    MODULE.validate_delivery(path, self.version)

    def test_rejects_missing_plate_enhancement_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.zip"
            self._write_zip(path, include_plate=False)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "plate_"):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_missing_agc_native_library(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.zip"
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
                path = Path(directory) / "delivery.zip"
                self._write_zip(path, **kwargs)
                with self.assertRaisesRegex(MODULE.DeliveryValidationError, message):
                    MODULE.validate_delivery(path, self.version)

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.zip"
            self._write_zip(path, tamper_checksum=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "checksum mismatch"):
                MODULE.validate_delivery(path, self.version)

    def test_rejects_oversized_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "delivery.zip"
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
