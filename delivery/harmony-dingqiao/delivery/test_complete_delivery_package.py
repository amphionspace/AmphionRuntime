"""Exercise complete ZIP layout with tiny synthetic SDKs, without rebuilding HARs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'delivery/harmony-dingqiao/delivery/pack_complete_asr_delivery.sh'


def digest(data):
    return hashlib.sha256(data).hexdigest()


class CompleteDeliveryPackageTest(unittest.TestCase):
    def test_relative_output_contains_default_layout_and_portable_checksums(self):
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            identity = {'schema_version': 3, 'build_mode': 'diagnostics', 'git_commit': commit, 'artifacts': {}}
            payloads = {}
            for name, path in {
                'amphion_asr.har': 'sdk/amphion_asr-diagnostics.har',
                'amphion_police.har': 'sdk/amphion_police-diagnostics.har',
                'amphion_dingqiao.har': 'sdk/amphion_dingqiao-diagnostics.har',
                'sherpa_onnx.har': 'sdk/sherpa_onnx.har',
                'amphion_asr_demo.hap': 'demo/amphion_asr_demo-diagnostics-signed.hap',
            }.items():
                payloads[path] = name.encode()
                identity['artifacts'][name] = {'sha256': digest(payloads[path])}
            with zipfile.ZipFile(work / 'debug.zip', 'w') as archive:
                for path, data in payloads.items():
                    archive.writestr('Amphion-ASR-Diagnostics-SDK/' + path, data)
                archive.writestr('Amphion-ASR-Diagnostics-SDK/tools/build-identity.json', json.dumps(identity))
            with zipfile.ZipFile(work / 'release.zip', 'w') as archive:
                archive.writestr('release/docs/BUILD_PROVENANCE.json', json.dumps({
                    'delivery_version': '0.3.13', 'source': {'commit': commit},
                    'verified_source_identity': {'git_commit': commit},
                }))
                archive.writestr('release/har/amphion_dingqiao.har', b'public-sdk')
            summary = work / 'ACCEPTANCE-SUMMARY.md'
            summary.write_text('synthetic build evidence\n')
            reports = []
            for mode in ['speaker-vad-turn', 'customer-ptt']:
                path = work / 'reports' / mode / 'report.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({'mode': mode, 'overall_status': 'PASS', 'build_identity': identity}))
                reports.append({'path': str(path.relative_to(work)), 'sha256': digest(path.read_bytes())})
            manifest = work / 'acceptance-manifest.json'
            manifest.write_text(json.dumps({'schema_version': 1, 'delivery_version': '0.3.13',
                'source_commit': commit, 'summary_sha256': digest(summary.read_bytes()), 'reports': reports}))
            env = dict(os.environ, AMPHION_RUNTIME_VERSION='0.3.13', RELEASE_SDK_ZIP=str(work/'release.zip'),
                       DIAGNOSTICS_SDK_ZIP=str(work/'debug.zip'), ACCEPTANCE_SUMMARY=str(summary),
                       ACCEPTANCE_MANIFEST=str(manifest))
            result = subprocess.run(['bash', str(SCRIPT), 'output'], cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            package = work / 'output/Amphion-Harmony-ASR-Complete-0.3.13.zip'
            checksum = Path(str(package)+'.sha256').read_text().split()
            self.assertEqual(checksum, [digest(package.read_bytes()), package.name])
            prefix = 'Amphion-Harmony-ASR-Complete-0.3.13/'
            with zipfile.ZipFile(package) as archive:
                names = archive.namelist()
                groups = {n[len(prefix):].split('/')[0] for n in names if n.startswith(prefix) and n != prefix}
                self.assertEqual(groups, {'README.md', 'release-sdk', 'diagnostics-sdk', 'diagnostics-demo', 'demo-source', 'docs'})
                self.assertEqual(archive.read(prefix+'demo-source/libs/amphion_dingqiao.har'), b'public-sdk')
                for item in reports:
                    self.assertEqual(digest(archive.read(prefix+'docs/'+item['path'])), item['sha256'])
                for line in archive.read(prefix+'docs/checksums.txt').decode().splitlines():
                    expected, relative = line.split(None, 1)
                    self.assertEqual(digest(archive.read(prefix+relative.removeprefix('./'))), expected)


if __name__ == '__main__':
    unittest.main()
