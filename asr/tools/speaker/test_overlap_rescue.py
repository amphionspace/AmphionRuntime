import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("12_eval_overlap_rescue.py")
SPEC = importlib.util.spec_from_file_location("overlap_rescue", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OverlapRescueTest(unittest.TestCase):
    class _TensorInfo:
        name = "tensor"

    class _Session:
        def get_inputs(self):
            return [OverlapRescueTest._TensorInfo()]

        def get_outputs(self):
            return [OverlapRescueTest._TensorInfo()]

        def run(self, _outputs, inputs):
            chunk = inputs["tensor"][0]
            return [np.stack([chunk, np.zeros_like(chunk)], axis=0)[None, :]]

    class _Stream:
        waveform = None

        def accept_waveform(self, sample_rate, waveform):
            self.waveform = waveform

        def input_finished(self):
            pass

    class _Extractor:
        def create_stream(self):
            return OverlapRescueTest._Stream()

        def is_ready(self, _stream):
            return True

        def compute(self, stream):
            if np.max(np.abs(stream.waveform)) > 0:
                return np.array([1.0, 0.0], dtype=np.float32)
            return np.array([0.0, 1.0], dtype=np.float32)

    def test_nearest_rank_percentile_matches_release_gate(self):
        self.assertEqual(MODULE.nearest_rank_percentile([1, 2, 3, 4], 0.95), 4)
        self.assertEqual(MODULE.nearest_rank_percentile([1, 2, 3, 4], 0.5), 2)

    def test_cosine_crossfade_has_complementary_overlap(self):
        ramp = MODULE.cosine_ramp(9)
        np.testing.assert_allclose(ramp + ramp[::-1], np.ones(9), atol=1e-6)
        self.assertEqual(float(ramp[0]), 0.0)
        self.assertEqual(float(ramp[-1]), 1.0)

    def test_customer_gate_is_strict(self):
        self.assertTrue(MODULE.case_gate("customer", "准备去上海", [1])[0])
        self.assertFalse(MODULE.case_gate("customer", "你好，准备去上海", [1])[0])
        self.assertFalse(MODULE.case_gate("customer", "准备去北京", [1])[0])

    def test_negative_gates_check_selection_and_text(self):
        self.assertTrue(MODULE.case_gate("target-only", "接到指令", [1, 0])[0])
        self.assertFalse(MODULE.case_gate("target-only", "", [1, 0])[0])
        self.assertTrue(MODULE.case_gate("other-only", "", [-1, -1])[0])
        self.assertFalse(MODULE.case_gate("other-only", "误选", [-1, -1])[0])
        self.assertFalse(MODULE.case_gate("other-only", "", [-1, 0])[0])

    def test_proc_status_parser_uses_kib_values(self):
        with tempfile.TemporaryDirectory() as directory:
            status = Path(directory) / "status"
            status.write_text(
                "VmRSS:\t1234 kB\nVmHWM:\t2345 kB\nVmData:\t3456 kB\nThreads:\t7\n",
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.read_proc_status(status),
                {"VmRSS": 1234, "VmHWM": 2345, "VmData": 3456, "Threads": 7},
            )

    def test_overlap_add_reconstructs_selected_stream_across_tail_chunk(self):
        samples = np.linspace(-0.5, 0.5, MODULE.CHUNK_SAMPLES + 1234, dtype=np.float32)
        enhanced, detail = MODULE.run_rescue(
            self._Session(),
            self._Extractor(),
            np.array([1.0, 0.0], dtype=np.float32),
            samples,
            threshold=0.25,
        )
        np.testing.assert_allclose(enhanced, samples, atol=1e-6)
        self.assertEqual(detail["selected"], [0, 0])

    def test_frozen_input_manifest_covers_every_release_case(self):
        manifest = MODULE.json.loads(
            MODULE.DEFAULT_INPUT_HASH_MANIFEST.read_text(encoding="utf-8")
        )
        expected = set(MODULE.ENROLLMENT_NAMES)
        expected.update(filename for _, filename, _ in MODULE.CUSTOMER_CASES)
        expected.update(filename for _, filename, _ in MODULE.NEGATIVE_CASES)
        self.assertEqual(set(manifest), expected)

    def test_require_sha256_rejects_same_name_with_different_content(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "model.onnx"
            artifact.write_bytes(b"expected")
            digest = MODULE.sha256(artifact)
            self.assertEqual(MODULE.require_sha256(artifact, digest, "model"), digest)
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                MODULE.require_sha256(artifact, "0" * 64, "model")


if __name__ == "__main__":
    unittest.main()
