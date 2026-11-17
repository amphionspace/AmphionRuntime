import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/NoiseSuppressionConfig.ts'


class NoiseSuppressionConfigTest(unittest.TestCase):
    def test_selection_legacy_defaults_and_conflicts(self):
        script = f"""
          import assert from 'node:assert/strict';
          import {{ noiseSuppressionModel as choose }} from {CONFIG.as_uri()!r};
          assert.equal(choose({{}}), 'none');
          assert.throws(()=>choose({{enableGtcrn:true}}),/removed/);
          assert.equal(choose({{enableGtcrn: 'true'}}), 'none');
          for (const name of ['none','deepfilternet3']) {{
            assert.equal(choose({{noiseSuppressionModel:name}}), name);
          }}
          for (const value of ['', 'deepfilter', 'gtcrn', 'ulunas', true, 1, null]) {{
            assert.throws(()=>choose({{noiseSuppressionModel:value}}));
          }}
        """
        subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', script],
                       check=True, cwd=ROOT)


if __name__ == '__main__':
    unittest.main()
