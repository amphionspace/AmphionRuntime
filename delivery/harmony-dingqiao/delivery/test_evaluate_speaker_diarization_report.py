from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).with_name("evaluate_speaker_diarization_report.py")
SPEC = importlib.util.spec_from_file_location("diarization_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def turn(start: float, end: float, speaker: int, **extra: object) -> dict:
    return dict(beginTime=start * 1000, endTime=end * 1000, speakerIndex=speaker, **extra)


class SpeakerIdentityStabilityTest(unittest.TestCase):
    def test_detects_same_person_changing_identity_after_another_person(self):
        result = MODULE.evaluate(
            [turn(0, 2, 0), turn(2, 4, 1), turn(4, 6, 2)],
            [(0, 2, "A"), (2, 4, "B"), (4, 6, "A")], 6,
        )["identityStability"]
        self.assertEqual(["A"], result["referenceSpeakersWithMultipleSystemIds"])
        self.assertEqual(1, result["sameSpeakerIdSwitchCount"])
        self.assertEqual(0, result["switches"][0]["fromSpeakerIndex"])
        self.assertEqual(2, result["switches"][0]["toSpeakerIndex"])
        self.assertEqual(4.255, result["switches"][0]["atSeconds"])

    def test_distinguishes_stable_arbitrary_indexes_unknown_and_overlap(self):
        result = MODULE.evaluate(
            [turn(0, 2, 3), turn(2, 3, -1),
             turn(3, 4, 0, secondarySpeakerIndexes=[3]),
             turn(4, 6, 3), turn(6, 8, 0)],
            [(0, 6, "A"), (3, 4, "B"), (6, 8, "B")], 8,
        )["identityStability"]
        self.assertEqual([], result["referenceSpeakersWithMultipleSystemIds"])
        self.assertEqual(0, result["sameSpeakerIdSwitchCount"])
        self.assertEqual(0.75, result["perReferenceLabelSeconds"]["A"]["unknown"])
        self.assertEqual({"0"}, set(result["perReferenceLabelSeconds"]["B"]))


if __name__ == "__main__":
    unittest.main()
