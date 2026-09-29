import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'asr/tools/delivery/dingqiao_build_provenance.sh'


class CommunityDeliveryAssetsTest(unittest.TestCase):
    def test_current_models_pass_and_missing_or_truncated_models_fail(self):
        models = {
            'eres2net.onnx': 30 * 1024 * 1024,
            'pyannote-segmentation-3.0.onnx': 5 * 1024 * 1024,
            'community-wespeaker-encoder.fp32.onnx': 21_301_300,
            'community-wespeaker-pool.fp32.onnx': 5_264_664,
            'community-feature.f32': 83_840,
            'community-plda.f64': 398_352,
        }
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'fixture.zip'
            cases = [(None, False)] + [(name, truncated)
                for name in models if name.startswith('community-')
                for truncated in (False, True)]
            for bad, truncated in cases:
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                    for name, size in models.items():
                        if name == bad and not truncated:
                            continue
                        z.writestr('assets/amphion-dingqiao/' + name,
                                   bytes(size - 1 if name == bad else size))
                    for name, size in [('lac_encoder.onnx', 20 * 1024 * 1024),
                                       ('lac_crf_transitions.npy', 1024),
                                       ('word.dic', 1024), ('tag.dic', 100)]:
                        z.writestr('assets/lac/v1/' + name, bytes(size))
                for kind in ('aar', 'apk'):
                    with self.subTest(kind=kind, missing=bad, truncated=truncated):
                        result = subprocess.run(
                            ['bash', '-c', 'source "$1"; dingqiao_verify_' + kind +
                             '_speaker_model "$2"', 'test', str(SCRIPT), str(archive)],
                            capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0 if bad is None else 1,
                                         result.stdout + result.stderr)
