import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('pack_sdk_only', Path(__file__).with_name('pack_sdk_only.py'))
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.android = self.root / 'android'
        (self.android / 'docs').mkdir(parents=True)
        for name in ('API.md', 'INTEGRATION.md', 'PSEUDOCODE.md', 'SDK_README.md'):
            (self.android / 'docs' / name).write_text('# Current docs\n')
        for name in ('LICENSE', 'NOTICE'):
            (self.android / name).write_text('Notice\n')
        (self.android / 'CHANGELOG.md').write_text('# Changelog\n\n## [3.1] - today\nCurrent\n\n## [0.1.0]\nObsolete\n')
        self.model = self.root / 'model'
        self.model.mkdir()
        for name in ('frontend_golden.json', 'export_report.json', 'model.onnx'):
            (self.model / name).write_bytes(b'fixture')
        self.manifest = {'model_id': 'fixture', 'version': '0.1.0', 'files': [
            {'name': n, 'size_bytes': 7} for n in ('frontend_golden.json', 'export_report.json', 'model.onnx')]}
        self.write_manifest()
        self.aar = self.root / 'sdk.aar'
        assets = self.root / 'assets'
        pack.stage_assets(self.model, assets)
        with zipfile.ZipFile(self.aar, 'w') as z:
            z.writestr('classes.jar', b'fixture')
            for path in assets.rglob('*'):
                if path.is_file():
                    z.write(path, 'assets/' + path.relative_to(assets).as_posix())
        self.output = self.root / 'lits-dingqiao-tts-android-sdk-vocos24k-3.1'

    def write_manifest(self):
        (self.model / 'manifest.json').write_text(json.dumps(self.manifest))

    def build(self):
        return pack.build(self.aar, self.model, self.android, self.output, '3.1')

    def test_customer_contents_keep_runtime_contract(self):
        archive = self.build()
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            self.assertFalse(any('/external-resources/' in n for n in names))
            self.assertFalse(any(n.endswith('/export_report.json') for n in names))
            self.assertFalse(any('/validation/' in n for n in names))
            self.assertNotIn('Obsolete', z.read(self.output.name + '/CHANGELOG.md').decode())
        with zipfile.ZipFile(self.aar) as z:
            manifest = json.loads(z.read('assets/lits-models/tts/fixture/0.1.0/manifest.json'))
            self.assertIn('assets/lits-models/tts/fixture/0.1.0/frontend_golden.json', z.namelist())
        self.assertNotIn('export_report.json', [x['name'] for x in manifest['files']])
        self.assertEqual(pack.sha256(self.aar), pack.sha256(next(self.output.glob('*.aar'))))

    def test_thin_aar_rejected(self):
        with zipfile.ZipFile(self.aar, 'w') as z:
            z.writestr('classes.jar', b'fixture')
        with self.assertRaisesRegex(ValueError, 'bundled resource list'):
            self.build()

    def test_same_size_model_change_rejected(self):
        (self.model / 'model.onnx').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'bundled manifest'):
            self.build()

    def test_staging_removes_previous_model(self):
        target = self.root / 'staging'
        pack.stage_assets(self.model, target)
        (target / 'stale.onnx').write_bytes(b'old')
        pack.stage_assets(self.model, target)
        self.assertFalse((target / 'stale.onnx').exists())

    def test_resource_traversal_rejected(self):
        self.manifest['files'].append({'name': '../secret.txt'})
        self.write_manifest()
        with self.assertRaises(ValueError):
            self.build()

    def test_broken_customer_doc_link_rejected(self):
        (self.android / 'docs/API.md').write_text('[internal report](../reports/old.md)')
        with self.assertRaisesRegex(ValueError, 'Broken documentation link'):
            self.build()

    def test_license_in_aar_rejected(self):
        with zipfile.ZipFile(self.aar, 'a') as z:
            z.writestr('assets/amphion-license.lic', 'fixture')
        with self.assertRaisesRegex(ValueError, 'Authorization'):
            self.build()


if __name__ == '__main__':
    unittest.main()
