from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("validate_asr_sdk_delivery.py")
SPEC = importlib.util.spec_from_file_location("validate_asr_sdk_delivery", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

FIXTURE_MODEL_MD5 = {
    "asset.onnx": hashlib.md5(b"approved source").hexdigest(),
}


class ValidateAsrSdkDeliveryTest(unittest.TestCase):
    def _write_fixture(
        self,
        root: Path,
        *,
        include_yue: bool = False,
        bad_model_hash: bool = False,
        duplicate_model_root: bool = False,
        embedded_license: bool = False,
        nested_version: str = "0.2.5",
        release_date: str = "2026-07-18",
    ) -> None:
        required = set(MODULE.REQUIRED_FILES)
        required.remove("har/amphion_dingqiao.har")
        required.remove("docs/BUILD_PROVENANCE.json")
        required.remove("docs/checksum.txt")
        for relative in required:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"fixture for {relative}\n", encoding="utf-8")
        (root / "README.md").write_text(
            "SDK-only，不包含独立 TTS SDK 或 TTS 模型。\n", encoding="utf-8"
        )

        har_path = root / "har/amphion_dingqiao.har"
        har_path.parent.mkdir(parents=True, exist_ok=True)
        model_payload = b"model"
        model_digest = "0" * 64 if bad_model_hash else hashlib.sha256(model_payload).hexdigest()
        bundles = {
            bundle: [
                {
                    "name": "asset.bin",
                    "size_bytes": len(model_payload),
                    "output_sha256": model_digest,
                    "source_name": "asset.onnx",
                    "source_md5": FIXTURE_MODEL_MD5["asset.onnx"],
                    "source_sha256": hashlib.sha256(b"unrelated diagnostic").hexdigest(),
                }
            ]
            for bundle in ("zh-en/v1", "punct-zhen/v1", "itn-zh/v1", "vad/v1")
        }
        if include_yue:
            bundles["yue-en/v1"] = []
        model_manifest = {"manifest_version": 2, "bundles": bundles}
        model_manifest_payload = json.dumps(model_manifest).encode("utf-8")
        with tarfile.open(har_path, "w:gz") as archive:
            self._add_json(archive, "package/oh-package.json5", {"version": "0.2.5"})
            for name in MODULE.VERSIONED_PACKAGE_PATHS:
                self._add_json(archive, name, {"version": nested_version})
            self._add_bytes(
                archive,
                MODULE.RUNTIME_IDENTITY_PATH,
                (
                    "export const HARMONY_SDK_VERSION: string = '0.2.5';\n"
                    "export const HARMONY_SDK_MAJOR: number = 1;\n"
                    f"export const HARMONY_SDK_RELEASE_DATE: string = '{release_date}';\n"
                ).encode("utf-8"),
            )
            self._add_bytes(archive, MODULE.MODEL_MANIFEST_PATH, model_manifest_payload)
            self._add_json(archive, MODULE.POLICE_MANIFEST_PATH, {"files": {}})
            for bundle in bundles:
                self._add_bytes(
                    archive,
                    f"{Path(MODULE.MODEL_MANIFEST_PATH).parent.as_posix()}/{bundle}/asset.bin",
                    model_payload,
                )
            if duplicate_model_root:
                self._add_bytes(
                    archive,
                    "package/_bundled/amphion_asr/src/main/resources/rawfile/"
                    "amphion-models 2/zh-en/v1/asset.bin",
                    b"duplicate",
                )
            if embedded_license:
                self._add_bytes(
                    archive,
                    "package/src/main/resources/rawfile/amphion-license.lic",
                    b"license",
                )

        provenance = {
            "delivery_version": "0.2.5",
            "asr_only": False,
            "sdk_only": True,
            "languages": ["zh-en"],
            "artifacts": [
                {
                    "path": "har/amphion_dingqiao.har",
                    "size_bytes": har_path.stat().st_size,
                    "sha256": hashlib.sha256(har_path.read_bytes()).hexdigest(),
                }
            ],
            "model": {
                "bundles": sorted(MODULE.ALLOWED_MODEL_BUNDLES),
                "manifest_sha256": hashlib.sha256(model_manifest_payload).hexdigest(),
                "manifest_version": 2,
                "onnx_md5": dict(sorted(FIXTURE_MODEL_MD5.items())),
            },
        }
        provenance_path = root / "docs/BUILD_PROVENANCE.json"
        provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        self._write_checksums(root)

    @staticmethod
    def _add_json(archive: tarfile.TarFile, name: str, value: object) -> None:
        payload = json.dumps(value).encode("utf-8")
        ValidateAsrSdkDeliveryTest._add_bytes(archive, name, payload)

    @staticmethod
    def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    @staticmethod
    def _write_checksums(root: Path) -> None:
        lines = []
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            relative = path.relative_to(root).as_posix()
            if relative == "docs/checksum.txt":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  ./{relative}\n")
        (root / "docs/checksum.txt").write_text("".join(lines), encoding="utf-8")

    def test_accepts_exact_zh_en_sdk_only_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_demo_or_tts_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            demo = root / "demo/dingqiao-demo.hap"
            demo.parent.mkdir()
            demo.write_bytes(b"hap")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "unexpected file"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_yue_model_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, include_yue=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "Yue|model bundles"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            (root / "README.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "checksum mismatch"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_model_content_that_does_not_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, bad_model_hash=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "model asset hash"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_self_consistent_model_that_is_not_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            wrong_identity = {
                "asset.onnx": hashlib.md5(b"other-model").hexdigest(),
            }
            with self.assertRaisesRegex(
                MODULE.DeliveryValidationError, "ONNX MD5 mismatch"
            ):
                MODULE.validate_delivery(root, "0.2.5", wrong_identity)

    def test_rejects_duplicate_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, duplicate_model_root=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "model root"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_embedded_license(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, embedded_license=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "forbidden HAR member"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_nested_package_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, nested_version="0.2.4")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "nested HAR version"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)

    def test_rejects_stale_release_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, release_date="2026-07-16")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "runtime identity"):
                MODULE.validate_delivery(root, "0.2.5", FIXTURE_MODEL_MD5)


if __name__ == "__main__":
    unittest.main()
