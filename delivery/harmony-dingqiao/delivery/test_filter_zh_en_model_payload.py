from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("filter_zh_en_model_payload.py")
SPEC = importlib.util.spec_from_file_location("filter_zh_en_model_payload", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FilterZhEnModelPayloadTest(unittest.TestCase):
    def _model_root(self, root: Path, *, omit: str = "") -> Path:
        model_root = root / "amphion-models"
        bundles = {}
        for bundle in sorted(MODULE.REQUIRED_BUNDLES | {"yue-en/v1"}):
            if bundle == omit:
                continue
            bundles[bundle] = [{"name": "asset.bin", "output_sha256": "fixture"}]
            asset = model_root / bundle / "asset.bin"
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(bundle.encode("utf-8"))
        (model_root / "README.md").write_text("models\n", encoding="utf-8")
        (model_root / "manifest.json").write_text(
            json.dumps({"manifest_version": 2, "bundles": bundles}), encoding="utf-8"
        )
        return model_root

    def test_removes_yue_payload_and_manifest_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_root = self._model_root(Path(directory))
            duplicate = model_root.parent / "amphion-models 2/yue-en/v1/model.bin"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_bytes(b"unexpected")
            (model_root.parent / ".DS_Store").write_bytes(b"metadata")
            MODULE.filter_payload(model_root)
            manifest = json.loads((model_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(MODULE.REQUIRED_BUNDLES, set(manifest["bundles"]))
            self.assertFalse((model_root / "yue-en").exists())
            self.assertTrue((model_root / "zh-en/v1/asset.bin").is_file())
            self.assertTrue((model_root / "README.md").is_file())
            self.assertFalse(duplicate.parent.parent.parent.exists())
            self.assertFalse((model_root.parent / ".DS_Store").exists())

    def test_rejects_missing_required_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_root = self._model_root(Path(directory), omit="vad/v1")
            with self.assertRaisesRegex(MODULE.PayloadFilterError, "missing required bundle"):
                MODULE.filter_payload(model_root)


if __name__ == "__main__":
    unittest.main()
