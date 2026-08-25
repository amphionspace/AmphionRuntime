import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFY_SCRIPT = REPO_ROOT / "asr/tools/verify_harmony_sherpa_symbols.py"
BUILD_SCRIPT = REPO_ROOT / "asr/tools/04_build_harmony_so.sh"
PACKAGE_SCRIPT = REPO_ROOT / "asr/tools/05_package_har_libs.sh"
SMOKE_SCRIPT = REPO_ROOT / (
    "delivery/harmony-dingqiao/delivery/build_install_smoke.sh"
)


class VerifyHarmonySherpaSymbolsTest(unittest.TestCase):
    def test_cli_rejects_a_library_missing_a_required_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            library = root / "libsherpa-onnx-c-api.so"
            library.touch()
            fake_nm = root / "llvm-nm"
            fake_nm.write_text(
                "#!/bin/sh\n"
                "echo '0000000000000000 T SherpaOnnxOnlineStreamGetEndpointReason'\n",
                encoding="utf-8",
            )
            os.chmod(fake_nm, 0o755)

            completed = subprocess.run(
                [
                    "python3",
                    str(VERIFY_SCRIPT),
                    "--library",
                    str(library),
                    "--nm",
                    str(fake_nm),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("SherpaOnnxOnlineStreamCommitRule3Segment", completed.stderr)

    def test_build_package_and_release_smoke_enforce_the_symbol_gate(self) -> None:
        verifier_name = "verify_harmony_sherpa_symbols.py"
        self.assertIn(verifier_name, BUILD_SCRIPT.read_text(encoding="utf-8"))
        self.assertIn(verifier_name, PACKAGE_SCRIPT.read_text(encoding="utf-8"))
        self.assertIn(verifier_name, SMOKE_SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
