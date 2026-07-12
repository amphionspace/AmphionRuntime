#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate_police_corpus as evaluation  # noqa: E402


class EvaluatePoliceCorpusTest(unittest.TestCase):
    def test_decode_utf16_hex_preserves_non_bmp_text(self) -> None:
        text = "冀R70624警情\U0001f4e2"
        encoded = text.encode("utf-16-be").hex()

        self.assertEqual(evaluation.decode_utf16_hex(encoded), text)

    def test_normalize_ignores_width_case_space_and_punctuation(self) -> None:
        self.assertEqual(evaluation.normalize(" 冀ｒ-７０６２４。"), "冀R70624")

    def test_edit_distance_counts_insert_delete_and_replace(self) -> None:
        self.assertEqual(evaluation.edit_distance("处警", "出井"), 2)
        self.assertEqual(evaluation.edit_distance("派出所", "派所"), 1)

    def test_select_cases_balances_each_category(self) -> None:
        cases: dict[str, dict[str, str]] = {}
        for theme in evaluation.THEMES:
            for index in range(5):
                source = f"{theme}/wavs/{index}.wav"
                cases[source] = {
                    "utt_id": f"{theme}-{index}",
                    "category": theme,
                    "reference": "警情",
                    "source": source,
                }

        selected = evaluation.select_cases(cases, 2)

        self.assertEqual(len(selected), 6)
        self.assertEqual(
            {theme: sum(case["category"] == theme for case in selected) for theme in evaluation.THEMES},
            {theme: 2 for theme in evaluation.THEMES},
        )


if __name__ == "__main__":
    unittest.main()
