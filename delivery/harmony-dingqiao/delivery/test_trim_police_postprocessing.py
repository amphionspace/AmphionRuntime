"""trim_police_postprocessing.py 的回归测试。

锁住两件容易回退的事：
  1. hotwords.json 必须活下来 —— 包 B 仍保留解码期热词偏置，删了它热词池就空了；
  2. manifest 必须打上 variant 标记 —— SDK 与 HAP 校验都靠它判定裁剪态。
"""

import json
import tempfile
import unittest
from pathlib import Path

import trim_police_postprocessing as trim

HOTWORDS = json.dumps({"plate": ["冀R"], "station": ["容城县公安局"], "terms": ["遣返"]},
                      ensure_ascii=False) + "\n"


def make_tree(root: Path) -> Path:
    police = root / trim.RELATIVE_ROOT
    (police / "lac/v1").mkdir(parents=True)
    (police / "police_terms").mkdir(parents=True)
    (police / "hotwords.json").write_text(HOTWORDS, encoding="utf-8")
    (police / "lac/v1/lac_encoder.onnx").write_bytes(b"x" * 2048)
    (police / "police_terms/terms_global.fst").write_bytes(b"y" * 512)
    files = {
        rel.relative_to(police).as_posix(): trim.sha256_of(rel)
        for rel in police.rglob("*") if rel.is_file()
    }
    (police / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": files,
                    "hotword_counts": {"plate": 1, "station": 1, "terms": 1}},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return police


class TrimPolicePostprocessingTest(unittest.TestCase):
    def test_keeps_hotwords_and_stamps_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            police = make_tree(Path(tmp))
            trim.trim(police)
            survivors = sorted(p.relative_to(police).as_posix()
                               for p in police.rglob("*") if p.is_file())
            self.assertEqual(survivors, ["hotwords.json", "manifest.json"])
            self.assertEqual((police / "hotwords.json").read_text(encoding="utf-8"), HOTWORDS)
            manifest = json.loads((police / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["variant"], "hotwords-only")
            self.assertEqual(set(manifest["files"]), {"hotwords.json"})
            # 热词条数留在 manifest 里，便于出包后核对池子没被动过。
            self.assertEqual(manifest["hotword_counts"], {"plate": 1, "station": 1, "terms": 1})

    def test_removes_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            police = make_tree(Path(tmp))
            trim.trim(police)
            self.assertFalse((police / "lac").exists())
            self.assertFalse((police / "police_terms").exists())

    def test_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            police = make_tree(Path(tmp))
            trim.trim(police)
            self.assertEqual(trim.trim(police), 0)

    def test_rejects_tampered_hotwords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            police = make_tree(Path(tmp))
            (police / "hotwords.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                trim.trim(police)

    def test_rejects_missing_hotwords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            police = make_tree(Path(tmp))
            (police / "hotwords.json").unlink()
            with self.assertRaises(SystemExit):
                trim.trim(police)


if __name__ == "__main__":
    unittest.main()
