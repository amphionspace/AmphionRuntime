"""Both platforms package and load the same quantized Community encoder the manifest describes."""
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

from asr.tools.tests.test_verify_community_encoder_mindir import MindirFixture
from asr.tools import verify_community_encoder_mindir as gate

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


class HvigorMindirAssetTest(MindirFixture):
    def setUp(self):
        super().setUp()
        hvigor = (ROOT / "asr/harmony/sdk-dingqiao/hvigorfile.ts").read_text()
        shared = hvigor[hvigor.index("const sharedModelFiles"):hvigor.index("];")]
        for name in re.findall(r"\x27([^\x27]+)\x27", shared):
            (self.shared / name).write_bytes(name.encode())
        # Only fixture source pins change; the actual Hvigor sync functions execute unchanged.
        self.hvigor = hvigor.replace("8f8c4619237d023770f5ed18012123771e216c5ec358987b8d3c4e486a74d30f",
                                     self.record["source"]["sha256"])
        self.hvigor = self.hvigor.replace("21_301_300", str(self.record["source"]["sizeBytes"]))

    def run_hvigor(self, succeeds=True):
        script = """
            const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
            const { isDeepStrictEqual } = require("node:util");
            const { stripTypeScriptTypes } = require("node:module");
            const vm = require("node:vm");
            const source = SOURCE.replace(/^import[^\\n]*;\\n/gm, "").replace("export default", "const buildConfig =");
            vm.runInNewContext(stripTypeScriptTypes(source), { fs, path, crypto, isDeepStrictEqual, harTasks: {},
                __dirname: MODULE_DIRECTORY });
        """.replace("SOURCE", json.dumps(self.hvigor)).replace(
            "MODULE_DIRECTORY", json.dumps(str(self.repo / "asr/harmony/sdk-dingqiao")))
        result = subprocess.run(["node", "--disable-warning=ExperimentalWarning", "-e", script],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(succeeds, result.returncode == 0, result.stderr)
        return result

    def test_cpu_build_without_ms_clears_the_previous_optional_copy(self):
        self.sync_generated()
        self.output.unlink()
        self.provenance.unlink()
        self.run_hvigor()
        self.assertFalse((self.generated / gate.MODEL_FILE).exists())
        self.assertTrue((self.generated / INT8).is_file())

    def test_verified_ms_is_copied_but_never_its_source_graph_or_sidecar(self):
        self.run_hvigor()
        self.assertEqual(self.output.read_bytes(), (self.generated / gate.MODEL_FILE).read_bytes())
        self.assertFalse((self.generated / gate.PROVENANCE_FILE).exists())
        self.assertFalse((self.generated / gate.SOURCE_FILE).exists())

    def test_missing_bad_and_orphan_provenance_fail_before_any_model_copy(self):
        original, output = self.provenance.read_bytes(), self.output.read_bytes()
        for mode in ["missing", "bad-json", "orphan", "wrong-flags", "wrong-source"]:
            with self.subTest(mode=mode):
                self.provenance.write_bytes(original)
                self.output.write_bytes(output)
                if mode == "missing":
                    self.provenance.unlink()
                elif mode == "bad-json":
                    self.provenance.write_text("not-json")
                elif mode == "orphan":
                    self.output.unlink()
                else:
                    record = json.loads(original)
                    if mode == "wrong-flags":
                        record["conversion"]["flags"] = ["--fp16=off"]
                    else:
                        record["source"]["file"] = INT8
                    self.provenance.write_text(json.dumps(record))
                self.run_hvigor(succeeds=False)
                self.assertFalse((self.generated / INT8).exists())

    def test_same_size_stale_target_is_refreshed_and_json_key_order_does_not_matter(self):
        self.sync_generated()
        (self.generated / gate.MODEL_FILE).write_bytes(self.output.read_bytes()[:-1] + b"!")
        self.provenance.write_text(json.dumps(self.record, sort_keys=True))
        self.run_hvigor()
        self.assertEqual(self.output.read_bytes(), (self.generated / gate.MODEL_FILE).read_bytes())

    def test_source_and_output_digest_changes_fail_before_copy(self):
        source = self.source.read_bytes()
        self.source.write_bytes(source[:-1] + b"!")
        self.run_hvigor(succeeds=False)
        self.source.write_bytes(source)
        self.output.write_bytes(self.output.read_bytes()[:-1] + b"!")
        self.run_hvigor(succeeds=False)
        self.assertFalse((self.generated / gate.MODEL_FILE).exists())

    def test_local_mindir_and_sidecar_are_ignored_in_shared_and_generated_paths(self):
        paths = [str(directory / name) for directory in [gate.SHARED_DIR, gate.GENERATED_DIR]
                 for name in [gate.MODEL_FILE, gate.PROVENANCE_FILE]]
        result = subprocess.run(["git", "check-ignore", "--stdin"], input="\n".join(paths) + "\n",
                                text=True, capture_output=True, cwd=ROOT, check=True)
        self.assertEqual(paths, result.stdout.splitlines())


if __name__ == '__main__':
    unittest.main()
