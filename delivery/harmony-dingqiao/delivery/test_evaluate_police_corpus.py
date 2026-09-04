#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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

    def test_evaluate_supplies_disabled_defaults_for_optional_stress_features(self) -> None:
        class ExpectedStop(Exception):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for theme in evaluation.THEMES:
                theme_dir = root / theme
                (theme_dir / "wavs").mkdir(parents=True)
                (theme_dir / "cases.tsv").write_text(
                    "utt_id\tref_text\taudio_path\n"
                    f"{theme}-1\t警情\twavs/{theme}-1.wav\n",
                    encoding="utf-8",
                )

            def assert_stress_defaults(args: SimpleNamespace) -> None:
                self.assertIsNone(args.target_speaker_manifest)
                self.assertIsNone(args.expected_tail_manifest)
                self.assertIsNone(args.speaker_vad_threshold)
                self.assertFalse(args.skip_target_content_check)
                self.assertFalse(args.installed_package)
                raise ExpectedStop

            args = SimpleNamespace(
                data_dir=root,
                device="device",
                limit_per_category=1,
                pace_ms=20,
                timeout=60,
                skip_build_install=True,
            )
            with mock.patch.object(evaluation, "run_stress", side_effect=assert_stress_defaults):
                with self.assertRaises(ExpectedStop):
                    evaluation.evaluate(args)


if __name__ == "__main__":
    unittest.main()
