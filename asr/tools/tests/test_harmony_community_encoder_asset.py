"""Both platforms package and load the same quantized Community encoder the manifest describes."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / 'delivery/harmony-dingqiao/delivery/community_diarization_1.json'
INT8 = 'community-wespeaker-encoder.int8.onnx'
FP32 = 'community-wespeaker-encoder.fp32.onnx'


class CommunityEncoderAssetTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text())
        self.files = {entry['file']: entry for entry in self.manifest['files']}

    def test_manifest_binds_the_int8_encoder_to_its_fp32_source(self):
        int8, fp32 = self.files[INT8], self.files[FP32]
        self.assertEqual(int8['sizeBytes'], 5_468_354)
        self.assertEqual(int8['derivedFrom'], FP32)
        quantization = self.manifest['encoderQuantization']
        self.assertEqual(quantization['runtimeFile'], INT8)
        self.assertEqual(quantization['source']['sha256'], fp32['sha256'])
        # The split exporter verifies its two outputs by position.
        self.assertEqual([entry['file'] for entry in self.manifest['files'][:2]],
                         [FP32, 'community-wespeaker-pool.fp32.onnx'])

    def test_harmony_packages_and_loads_only_the_int8_encoder(self):
        hvigor = (ROOT / 'asr/harmony/sdk-dingqiao/hvigorfile.ts').read_text()
        shared = hvigor[hvigor.index('const sharedModelFiles'):hvigor.index('];')]
        self.assertIn(f"'{INT8}'", shared)
        self.assertNotIn(FP32, shared)
        native = (ROOT / 'asr/harmony/sdk/src/main/cpp/community_diarization.cpp').read_text()
        self.assertIn(f'"amphion-dingqiao/{INT8}"', native)
        self.assertNotIn(f'"amphion-dingqiao/{FP32}"', native)
        identity = (ROOT / 'delivery/harmony-dingqiao/delivery/harmony_build_identity.py').read_text()
        self.assertIn(f'"resources/rawfile/amphion-dingqiao/{INT8}"', identity)

    def test_android_packages_installs_and_replaces_the_fp32_encoder(self):
        gradle = (ROOT / 'asr/android/sdk-dingqiao/build.gradle.kts').read_text()
        self.assertIn(f'"{INT8}"', gradle)
        self.assertNotIn(f'"{FP32}"', gradle)
        assets = (ROOT / 'asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/'
                  'DingqiaoSpeakerModelAssets.kt').read_text()
        self.assertIn(f'"{INT8}" to {self.files[INT8]["sizeBytes"]:_}L', assets)
        self.assertIn(f'File(workPath, "{FP32}").delete()', assets)

    def test_local_model_matches_the_manifest_when_present(self):
        path = ROOT / 'shared/models/asr/dingqiao' / INT8
        if not path.exists():
            self.skipTest('model assets are restored from storage, not tracked')
        self.assertEqual(path.stat().st_size, self.files[INT8]['sizeBytes'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.files[INT8]['sha256'])


if __name__ == '__main__':
    unittest.main()
