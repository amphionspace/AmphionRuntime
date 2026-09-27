"""Run with WeTextProcessing installed; WEITN_FST_DIR can select packaged graphs."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from itn.chinese.inverse_normalizer import InverseNormalizer

from asr.tools.build_weitn_fsts import build


class WeitnFstsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = os.environ.get("WEITN_FST_DIR")
        if selected:
            cls.root = Path(selected)
        else:
            cls.temp = tempfile.TemporaryDirectory()
            cls.addClassCleanup(cls.temp.cleanup)
            cls.root = Path(cls.temp.name)
            build(cls.root)
        cls.normalizer = InverseNormalizer(cache_dir=str(cls.root), overwrite_cache=False)

    def test_preserves_recognized_interjections(self):
        for text in ("今天天气很好啊", "啊今天天气很好", "今天啊天气很好", "啊", "呃",
                     "呃今天天气很好啊", "今天天气很好呀", "今天天气很好呢"):
            with self.subTest(text=text):
                self.assertEqual(text, self.normalizer.normalize(text))

    def test_keeps_numeric_normalization(self):
        cases = {
            "今天天气很好": "今天天气很好",
            "二零二六年五月十五日": "2026/05/15",
            "百分之五十": "50%",
            "一百二十三元": "¥123",
            "二零二六年五月十五日啊": "2026/05/15啊",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(expected, self.normalizer.normalize(text))

    def test_tagger_is_unchanged(self):
        self.assertEqual(
            "4983ab817f3f3b206516d576b54d6f925c3a52c58c8348d3ae98e826b4f6d49d",
            hashlib.sha256((self.root / "zh_itn_tagger.fst").read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
