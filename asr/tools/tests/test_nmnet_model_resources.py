"""Exercise the actual shared synchronizer with small, independently hashed fixtures."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from asr.tools.verify_nmnet_package import verify_archive

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'asr/tools/nmnet_model_resources.cjs'
MANIFEST = ROOT / 'shared/models/asr/dingqiao/nmnet-student/v1/manifest.json'


class ResourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.target = Path(self.temp.name) / 'target'
        self.source.mkdir()
        self.record = json.loads(MANIFEST.read_text())
        for i, entry in enumerate(self.record['files']):
            data = bytes([i + 1]) * (31 + i)
            (self.source / entry['file']).write_bytes(data)
            entry.update(sizeBytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        for name in ['NOTICE.md', 'ECAPA-MODEL-CARD.md', 'ECAPA-LICENSE']:
            (self.source / name).write_text(name)
        self.save()

    def save(self):
        (self.source / 'manifest.json').write_text(json.dumps(self.record))

    def sync(self, ok=True):
        js = 'const r=require(process.argv[1]); r.sync(process.argv[2],process.argv[3]);'
        p = subprocess.run(['node', '-e', js, str(SCRIPT), str(self.source), str(self.target)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode == 0, ok, p.stderr)

    def test_roundtrip_and_same_size_cache_corruption_repaired(self):
        self.sync()
        name = self.record['files'][0]['file']
        (self.target / name).write_bytes(b'x' * self.record['files'][0]['sizeBytes'])
        self.sync()
        for entry in self.record['files']:
            self.assertEqual((self.source / entry['file']).read_bytes(),
                             (self.target / entry['file']).read_bytes())

    def test_bad_source_does_not_mutate_existing_package(self):
        self.sync()
        before = {p.name: p.read_bytes() for p in self.target.iterdir()}
        for damage in ['missing', 'same_size', 'truncated']:
            with self.subTest(damage=damage):
                name = self.record['files'][-1]['file']
                p = self.source / name
                original = p.read_bytes()
                if damage == 'missing':
                    p.unlink()
                else:
                    p.write_bytes(b'x' * (len(original) if damage == 'same_size' else 1))
                self.sync(False)
                self.assertEqual(before, {p.name: p.read_bytes() for p in self.target.iterdir()})
                p.write_bytes(original)

    def test_wrong_order_and_path_escape_rejected(self):
        original = self.record['files'][0]['file']
        for name in ['../escape.onnx', self.record['files'][1]['file']]:
            self.record['files'][0]['file'] = name
            self.save()
            self.sync(False)
            self.assertFalse(self.target.exists())
        self.record['files'][0]['file'] = original

    def test_manifest_is_student_and_native_order_matches(self):
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest['checkpointSha256'],
                         'f980c146e2c59f723e3808d4a76adb4731ccd674537d3aae3dc23ef445fab7c7')
        header = (ROOT / 'asr/harmony/sdk/src/main/cpp/nmnet_diarization.h').read_text()
        offsets = [header.index('"' + entry['file'] + '"') for entry in manifest['files']]
        self.assertEqual(offsets, sorted(offsets))

    def test_packaged_assets_require_matching_bytes_and_manifest(self):
        for prefix in ['assets/', 'resources/rawfile/']:
            archive = Path(self.temp.name) / 'fixture.zip'
            for damage in [None, 'model', 'manifest', 'notice', 'legacy']:
                with self.subTest(prefix=prefix, damage=damage):
                    with zipfile.ZipFile(archive, 'w') as output:
                        if damage == 'legacy':
                            output.writestr(prefix + 'amphion-dingqiao/community-plda.f64', b'old')
                        for p in self.source.iterdir():
                            data = p.read_bytes()
                            if ((damage == 'model' and p.name == self.record['files'][0]['file']) or
                                (damage == 'manifest' and p.name == 'manifest.json') or
                                (damage == 'notice' and p.name == 'NOTICE.md')):
                                data = b'{}'
                            output.writestr(prefix + 'amphion-dingqiao/nmnet-student/v1/' + p.name, data)
                    if damage:
                        with self.assertRaises(ValueError):
                            verify_archive(archive, self.source / 'manifest.json')
                    else:
                        self.assertEqual(len(verify_archive(archive, self.source / 'manifest.json')), 5)


if __name__ == '__main__':
    unittest.main()
