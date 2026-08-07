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
import zipfile


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
        police_dependency: str = "file:./_bundled/amphion_police",
        police_asset_payload: bytes = b"police-asset",
        nested_version: str = "0.3.0",
        release_date: str = "2026-08-07",
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
            "SDK-only，不包含独立 TTS SDK、TTS 模型或授权文件。"
            "内置警务文本增强，可通过 enablePoliceEnhancement 关闭。\n",
            encoding="utf-8",
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
            self._add_json(archive, "package/oh-package.json5", {
                "version": "0.3.0",
                "dependencies": {"amphion_police": police_dependency},
            })
            for name in MODULE.VERSIONED_PACKAGE_PATHS:
                self._add_json(archive, name, {"version": nested_version})
            self._add_json(archive, MODULE.POLICE_PACKAGE_PATH, {
                "version": "0.3.0",
                "dependencies": {"amphion_asr": "file:../amphion_asr"},
            })
            self._add_bytes(
                archive,
                "package/_bundled/amphion_police/Index.ets",
                b"export * from './src/main/ets/com/amphion/police/PoliceEnhancePipeline';\n",
            )
            self._add_bytes(
                archive,
                "package/_bundled/amphion_police/src/main/ets/com/amphion/police/PoliceEnhancePipeline.ets",
                b"export class PoliceEnhancePipeline {}\n",
            )
            police_asset_name = "police_terms/terms.tsv"
            self._add_json(archive, MODULE.POLICE_MANIFEST_PATH, {
                "schema_version": 1,
                "files": {
                    police_asset_name: hashlib.sha256(b"police-asset").hexdigest(),
                },
            })
            self._add_bytes(
                archive,
                f"{MODULE.POLICE_ASSET_ROOT.as_posix()}/{police_asset_name}",
                police_asset_payload,
            )
            self._add_bytes(
                archive,
                MODULE.RUNTIME_IDENTITY_PATH,
                (
                    "export const HARMONY_SDK_VERSION: string = '0.3.0';\n"
                    "export const HARMONY_SDK_MAJOR: number = 1;\n"
                    f"export const HARMONY_SDK_RELEASE_DATE: string = '{release_date}';\n"
                ).encode("utf-8"),
            )
            self._add_bytes(archive, MODULE.MODEL_MANIFEST_PATH, model_manifest_payload)
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
            "delivery_version": "0.3.0",
            "asr_only": True,
            "sdk_only": True,
            "languages": ["zh-en"],
            "capabilities": [
                "asr",
                "voiceprint",
                "punctuation",
                "itn",
                "vad",
                "industry-text-enhancement",
            ],
            "excluded_capabilities": [],
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

    @staticmethod
    def _write_zip(root: Path, destination: Path) -> None:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{root.name}/{path.relative_to(root).as_posix()}")

    def test_accepts_exact_zh_en_sdk_only_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_accepts_final_zh_en_sdk_only_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "amphion-harmony-asr-sdk-v0.3.0-20260807"
            self._write_fixture(root)
            delivery_zip = base / "delivery.zip"
            self._write_zip(root, delivery_zip)
            MODULE.validate_delivery_path(delivery_zip, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_final_zip_with_unexpected_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "amphion-harmony-asr-sdk-v0.3.0-20260807"
            self._write_fixture(root)
            demo = root / "demo/dingqiao-demo.hap"
            demo.parent.mkdir()
            demo.write_bytes(b"hap")
            delivery_zip = base / "delivery.zip"
            self._write_zip(root, delivery_zip)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "unexpected file"):
                MODULE.validate_delivery_path(delivery_zip, "0.3.0", FIXTURE_MODEL_MD5)

    def test_accepts_documented_police_enhancement_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            integration = root / "docs/INTEGRATION.md"
            integration.write_text(
                "警务增强可通过 enablePoliceEnhancement 开关控制。\n",
                encoding="utf-8",
            )
            self._write_checksums(root)
            MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_demo_or_tts_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            demo = root / "demo/dingqiao-demo.hap"
            demo.parent.mkdir()
            demo.write_bytes(b"hap")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "unexpected file"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_yue_model_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, include_yue=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "Yue|model bundles"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            (root / "README.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "checksum mismatch"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_model_content_that_does_not_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, bad_model_hash=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "model asset hash"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

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
                MODULE.validate_delivery(root, "0.3.0", wrong_identity)

    def test_rejects_duplicate_model_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, duplicate_model_root=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "model root"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_embedded_license(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, embedded_license=True)
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "forbidden HAR member"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_tampered_police_enhancement_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, police_asset_payload=b"tampered")
            with self.assertRaisesRegex(
                MODULE.DeliveryValidationError, "police enhancement asset hash mismatch"
            ):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_external_police_enhancement_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, police_dependency="file:../amphion_police")
            with self.assertRaisesRegex(
                MODULE.DeliveryValidationError, "does not link bundled police enhancement"
            ):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_nested_package_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, nested_version="0.2.4")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "nested HAR version"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_external_license_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            license_path = root / "license/amphion-license.lic"
            license_path.parent.mkdir(parents=True)
            license_path.write_text("license", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "unexpected file"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)

    def test_rejects_stale_release_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root, release_date="2026-07-16")
            with self.assertRaisesRegex(MODULE.DeliveryValidationError, "runtime identity"):
                MODULE.validate_delivery(root, "0.3.0", FIXTURE_MODEL_MD5)


if __name__ == "__main__":
    unittest.main()
