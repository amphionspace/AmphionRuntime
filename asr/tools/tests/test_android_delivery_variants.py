"""Small archives exercise variant selection without models or Gradle builds."""
from pathlib import Path
import io
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
MERGER = ROOT / 'asr/tools/delivery/merge_dingqiao_fat_aar.sh'
PACKER = ROOT / 'asr/tools/delivery/pack_dingqiao_customer_delivery.sh'


def archive_bytes(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        for name, value in files.items():
            z.writestr(name, value)
    return data.getvalue()


class AndroidDeliveryVariantsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ar = self.root / 'asr/android'
        scripts = self.root / 'asr/tools/delivery'
        scripts.mkdir(parents=True)
        shutil.copy2(MERGER, scripts / MERGER.name)
        self.script = scripts / MERGER.name
        # The production checks have their own tests; this fixture isolates which
        # built components reach the customer archive (including no fallback).
        (scripts / 'dingqiao_build_provenance.sh').write_text('''
dingqiao_repo_root_from_script() { printf '%s\\n' "$FIXTURE_ROOT"; }
dingqiao_ar_root_from_repo() { printf '%s/asr/android\\n' "$1"; }
dingqiao_load_git_provenance() { GIT_COMMIT_SHORT=fixture; }
dingqiao_assert_reproducible_build() { :; }
dingqiao_assert_sdk_version_consistent() { SDK_VERSION=0.3.5; GIT_COMMIT_FULL=fixture; }
dingqiao_resolve_delivery_version() { echo 0.3.5; }
dingqiao_embed_aar_build_manifest() { echo "variant=$DINGQIAO_BUILD_VARIANT" > "$1/META-INF/variant"; }
dingqiao_verify_aar_provenance() { :; }
dingqiao_verify_aar_native_libs() { :; }
dingqiao_verify_aar_speaker_model() { :; }
dingqiao_verify_aar_asr_models() { :; }
''')
        (self.root / 'asr/tools/verify_packed_model_assets.py').write_text('')
        for module in ['sdk', 'sdk-police', 'sdk-dingqiao']:
            base = self.ar / module
            (base / 'build/outputs/aar').mkdir(parents=True)
            (base / 'consumer-rules.pro').write_text('-dontwarn java.lang.invoke.StringConcatFactory\n')
            for variant in ['release', 'debug', 'diagnostics']:
                key = f'{module}-{variant}'
                (base / f'build/outputs/aar/{module}-{variant}.aar').write_bytes(archive_bytes({
                    'classes.jar': archive_bytes({f'{module}.class': key}),
                    f'assets/{module}.txt': key,
                    'assets/amphion-models/manifest.json': '{}',
                    'AndroidManifest.xml': key,
                }))
        for variant in ['debug', 'release']:
            jar = self.ar / f'sdk/build/intermediates/compile_library_classes_jar/{variant}/bundleLibCompileToJar{variant.title()}/classes.jar'
            jar.parent.mkdir(parents=True)
            jar.write_bytes(archive_bytes({'sdk.class': f'core-{variant}-unminified'}))
        self.env = dict(os.environ, FIXTURE_ROOT=str(self.root))

    def merge(self, *args):
        return subprocess.run(['bash', str(self.script), *args], env=self.env, text=True, capture_output=True)

    def check_variant(self, diagnostics):
        result = self.merge(*(['--diagnostics'] if diagnostics else []), '0.3.5')
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        suffix = '-diagnostics' if diagnostics else ''
        with zipfile.ZipFile(self.ar / f'build/dingqiao-delivery/dingqiao-asr{suffix}-v0.3.5.aar') as z:
            with zipfile.ZipFile(io.BytesIO(z.read('classes.jar'))) as classes:
                core = 'debug' if diagnostics else 'release'
                adapter = 'diagnostics' if diagnostics else 'release'
                self.assertEqual(f'core-{core}-unminified'.encode(), classes.read('sdk.class'))
                self.assertEqual(f'sdk-police-{core}'.encode(), classes.read('sdk-police.class'))
                self.assertEqual(f'sdk-dingqiao-{adapter}'.encode(), classes.read('sdk-dingqiao.class'))
            self.assertEqual(f'sdk-dingqiao-{adapter}'.encode(), z.read('AndroidManifest.xml'))
            self.assertEqual(f'variant={adapter}\n'.encode(), z.read('META-INF/variant'))

    def test_release_keeps_release_components(self):
        self.check_variant(False)

    def test_diagnostics_uses_debug_core_and_tracing_adapter(self):
        self.check_variant(True)

    def test_missing_diagnostics_does_not_silently_use_release(self):
        (self.ar / 'sdk-dingqiao/build/outputs/aar/sdk-dingqiao-diagnostics.aar').unlink()
        result = self.merge('--diagnostics')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('sdk-dingqiao-diagnostics.aar', result.stderr)

    def test_staging_rejects_preview_or_existing_directory(self):
        for args in [['--preview', '--stage-release', str(self.root / 'new')], ['--stage-release', str(self.root)]]:
            result = subprocess.run(['bash', str(PACKER), *args], text=True, capture_output=True)
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertIn('new absolute directory', result.stderr)


class AndroidItnVerbalizerTest(unittest.TestCase):
    def test_approved_small_rules_pass_and_truncated_or_padded_rules_fail(self):
        from asr.tools.delivery.verify_android_itn_verbalizer import ENTRY, verify
        import hashlib
        approved = b'optimized-fst' * 100
        expected = hashlib.sha256(approved).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sdk.aar'
            for payload in [approved, approved[:-1], approved + bytes(200_000)]:
                path.write_bytes(archive_bytes({ENTRY: payload}))
                if payload == approved:
                    verify(path, expected_sha256=expected)
                else:
                    with self.assertRaisesRegex(ValueError, 'approved rules'):
                        verify(path, expected_sha256=expected)
            path.write_bytes(archive_bytes({'unrelated': approved}))
            with self.assertRaises(KeyError):
                verify(path, expected_sha256=expected)
