from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("optimize_onnx_graphs.py")
SPEC = importlib.util.spec_from_file_location("optimize_onnx_graphs", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ManifestRewriteTest(unittest.TestCase):
    def test_write_manifest_refreshes_sizes_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for bundle, names in MODULE.EXPECTED_BUNDLES.items():
                bundle_dir = root / bundle
                bundle_dir.mkdir(parents=True)
                for name in names:
                    (bundle_dir / name).write_bytes(f"{bundle}/{name}\n".encode("utf-8"))

            MODULE.write_manifest(root)

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(1, manifest["manifest_version"])
            for bundle, names in MODULE.EXPECTED_BUNDLES.items():
                entries = {entry["name"]: entry for entry in manifest["bundles"][bundle]}
                self.assertEqual(set(names), set(entries))
                for name in names:
                    path = root / bundle / name
                    self.assertEqual(path.stat().st_size, entries[name]["size_bytes"])
                    self.assertEqual(MODULE.sha256_file(path), entries[name]["sha256"])

    def test_iter_expected_onnx_uses_manifest_order(self) -> None:
        root = Path("/models")

        self.assertEqual(
            [
                root / "zh-en/v1/encoder.int8.onnx",
                root / "zh-en/v1/decoder.onnx",
                root / "zh-en/v1/joiner.int8.onnx",
                root / "yue-en/v1/encoder.int8.onnx",
                root / "yue-en/v1/decoder.onnx",
                root / "yue-en/v1/joiner.int8.onnx",
                root / "punct-zhen/v1/model.int8.onnx",
                root / "vad/v1/silero_vad.onnx",
            ],
            list(MODULE.iter_expected_onnx(root)),
        )


if __name__ == "__main__":
    unittest.main()
