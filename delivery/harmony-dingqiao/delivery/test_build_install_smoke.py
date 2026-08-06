from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).with_name("build_install_smoke.sh")


class BuildInstallSmokeTest(unittest.TestCase):
    def test_hvigor_failures_stop_the_isolated_build(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        source = SCRIPT.read_text(encoding="utf-8")
        install = source.index('"$OHPM" install --all')
        assemble_hap = source.index('if ! "$NODE" "$HVIGOR" assembleHap')
        self.assertLess(install, assemble_hap)
        self.assertIn('if ! "$NODE" "$HVIGOR" assembleHap', source)
        self.assertIn('if ! "$NODE" "$HVIGOR" assembleHar', source)

    def test_target_speaker_override_uses_the_formal_ort_asset_name(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("convtasnet_16k.ort", source)
        self.assertNotIn("convtasnet_16k.onnx", source)


if __name__ == "__main__":
    unittest.main()
