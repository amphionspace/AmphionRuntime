#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("run_hotword_device_eval.py")
SPEC = importlib.util.spec_from_file_location("run_hotword_device_eval", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HotwordDeviceEvalTest(unittest.TestCase):
    def test_checked_in_fixture_is_fixed_and_balanced(self) -> None:
        entries = MODULE.verify_fixture(MODULE.DEFAULT_FIXTURE)
        self.assertEqual(400, len(entries))
        self.assertEqual(200, sum(entry["language"] == "zh-CN" for entry in entries))
        self.assertEqual(200, sum(entry["language"] == "en-US" for entry in entries))
        self.assertEqual(400, len({(entry["language"], entry["recording_id"]) for entry in entries}))
        strata: dict[str, int] = {}
        for entry in entries:
            strata[str(entry["stratum"])] = strata.get(str(entry["stratum"]), 0) + 1
        self.assertEqual([50] * 8, sorted(strata.values()))

    def test_normalization_and_metrics(self) -> None:
        self.assertEqual(list("易心莹"), MODULE.normalize_zh("易，心莹。"))
        self.assertEqual(["illana", "bay"], MODULE.normalize_en("Illana Bay!"))
        self.assertTrue(MODULE.hotword_hit("THE CITY FACES ILLANA BAY。", "Illana Bay", "en-US"))
        self.assertTrue(MODULE.hotword_hit("易心莹大师", "易心莹", "zh-CN"))
        self.assertEqual(1, MODULE.edit_distance(["a", "b"], ["a", "c"]))

    def test_negative_and_lac_fixtures_are_fixed(self) -> None:
        fixture_dir = MODULE.DEFAULT_FIXTURE.parent
        negative = MODULE.verify_fixture(fixture_dir / "hotword_negative_200.jsonl")
        self.assertEqual(200, len(negative))
        self.assertEqual(200, len({(entry["dataset_id"], entry["recording_id"])
                                  for entry in negative}))
        for entry in negative:
            self.assertTrue(entry["negative_control"])
            self.assertIn(entry["expected_source"], entry["reference"])
            self.assertNotIn(entry["distractor"], entry["reference"])
            self.assertEqual([entry["distractor"]], entry["hotwords"])
            self.assertIn(entry["candidate_length"], {3, 4, 5, 6})

        lac = MODULE.verify_fixture(fixture_dir / "hotword_lac_400.jsonl")
        self.assertEqual(400, len(lac))
        self.assertEqual(200, sum(bool(entry.get("negative_control")) for entry in lac))
        self.assertEqual(200, sum(not bool(entry.get("negative_control")) for entry in lac))

    def test_device_manifest_uses_bilingual_engine_selector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "DATA_ASR" / "sample.wav"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source")
            payload = root / "payload"
            entries = [{"id": "hw-100", "language": "en-US", "audio": "sample.wav",
                        "hotwords": ["Illana Bay"]}]

            def fake_convert(_source: Path, destination: Path) -> int:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"pcm")
                return 3

            with mock.patch.object(MODULE, "convert_to_pcm", side_effect=fake_convert):
                self.assertEqual(3, MODULE.prepare_payload(entries, root, payload, "/remote"))
            manifest = json.loads((payload / "manifest.jsonl").read_text(encoding="utf-8"))
            self.assertEqual("zh-CN", manifest["language"])
            self.assertEqual(["Illana Bay"], manifest["hotwords"])


if __name__ == "__main__":
    unittest.main()
