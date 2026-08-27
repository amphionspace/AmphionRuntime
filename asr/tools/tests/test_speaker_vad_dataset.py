from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "speaker" / "06_eval_speaker_vad_aidatatang.py"
SPEC = importlib.util.spec_from_file_location("speaker_vad_dataset", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SpeakerVadDatasetTest(unittest.TestCase):
    def test_aishell3_obs_bundle_manifests_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio" / "speaker" / "input.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"wav")
            recordings = root / "aishell3_test_hotwords_500_recordings_packaged.jsonl.gz"
            supervisions = root / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz"
            with gzip.open(recordings, "wt", encoding="utf-8") as output:
                output.write(json.dumps({
                    "id": "recording-1",
                    "sources": [{"source": "audio/speaker/input.wav"}],
                }) + "\n")
            with gzip.open(supervisions, "wt", encoding="utf-8") as output:
                output.write(json.dumps({
                    "recording_id": "recording-1",
                    "speaker": "speaker-1",
                    "duration": 1.25,
                    "text": "测试",
                }) + "\n")

            samples = MODULE.load_samples(root)

            self.assertEqual(1, len(samples))
            self.assertEqual("speaker-1", samples[0].speaker)
            self.assertEqual(audio, samples[0].audio_path)


if __name__ == "__main__":
    unittest.main()
