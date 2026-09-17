"""Input validation guards; full model parity is checked during export."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import export_intmeanflow_student as exporter


class ExportInputTest(unittest.TestCase):
    def test_invalid_temperature_is_rejected_before_loading_inputs(self):
        for temperature in ("-1", "nan", "inf"):
            argv = [
                "export",
                "--distill-source",
                ".",
                "--checkpoint",
                "missing.pt",
                "--frontend-assets",
                ".",
                "--vocos",
                "missing.onnx",
                "--output",
                "unused",
                f"--temperature={temperature}",
            ]
            with self.subTest(temperature=temperature), patch("sys.argv", argv):
                error = io.StringIO()
                with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
                    exporter.parse_args()
                self.assertIn(
                    "temperature must be finite and nonnegative", error.getvalue()
                )

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            checkpoint = root / "checkpoint.pt"
            checkpoint.touch()
            vocos = root / "vocos.onnx"
            vocos.touch()
            marker = source / "keep.txt"
            marker.write_text("keep this data")
            argv = [
                "export",
                "--distill-source",
                str(source),
                "--checkpoint",
                str(checkpoint),
                "--frontend-assets",
                str(source),
                "--vocos",
                str(vocos),
                "--output",
                str(source),
            ]
            with patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    exporter.parse_args()
            self.assertEqual("keep this data", marker.read_text())

    def test_unsupported_sampling_grid_does_not_construct_a_model(self):
        model = Mock()
        checkpoint = {"metadata": {"student_t_grid": [0.0, 1.0]}}
        with self.assertRaisesRegex(ValueError, "trained two-step grid"):
            exporter.load_student(checkpoint, model, Mock())
        model.assert_not_called()

    def test_reordered_training_tokens_are_rejected(self):
        symbols = exporter.read_json(exporter.FRONTEND_DIR / "zh_en_symbols.json")[
            "symbols"
        ]
        symbols[4], symbols[5] = symbols[5], symbols[4]
        with self.assertRaisesRegex(ValueError, "Training token IDs differ"):
            exporter.validate_frontend(Path("unused"), symbols, Mock())


if __name__ == "__main__":
    unittest.main()
