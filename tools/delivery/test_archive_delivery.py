import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('archive_delivery', Path(__file__).with_name('archive_delivery.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.uploads = []
        self.corrupt = None
        self.fail_index = False
        self.change_source = None

    def check_remote(self):
        pass

    def push(self, source, uri, preview=False):
        if uri in self.objects and self.objects[uri] != source.read_bytes():
            raise ValueError('conflict')
        if not preview:
            self.uploads.append(uri)
            self.objects[uri] = source.read_bytes()

    def pull(self, uri, destination):
        if self.fail_index and '/archive-index/' in uri:
            raise ValueError('index download failed')
        data = self.objects[uri]
        destination.write_bytes(b'corrupt' if self.corrupt and self.corrupt in uri else data)
        if self.change_source and '/archive-index/' in uri:
            self.change_source.write_bytes(b'changed')


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root/'repo'
        (self.repo/'delivery').mkdir(parents=True)
        self.index = self.repo/'delivery/published-artifact-archives.json'
        self.old = {'schema_version': 1, 'archives': [{'remote_uri': 'existing', 'sha256': 'old'}]}
        module.write_json(self.index, self.old)
        self.staging = self.root/'staging'
        self.stage = self.staging/'asr/android/0.3.9'/('a'*40)
        (self.stage/'packages').mkdir(parents=True)
        self.outer = self.stage/'packages/full.zip'
        self.outer.write_bytes(b'original complete delivery')
        self.record = dict(platform='android', version='0.3.9', source_commit='a'*40,
                           artifact='full.zip', published=False, **module.identity(self.outer))
        module.write_json(self.repo/'delivery/record.json', self.record)
        self.checksum = self.stage/'packages/full.zip.sha256'
        self.checksum.write_text(self.record['sha256']+'  full.zip\n')
        self.args = argparse.Namespace(record='delivery/record.json', publication='unpublished',
            companion=[], batch_id='test-archive', apply=True, remove_local=True)
        self.bucket = FakeBucket()

    def run_archive(self):
        with patch.object(module, 'unused'):
            return module.archive(self.args, self.bucket, self.repo, self.staging)

    def assert_retained(self):
        self.assertTrue(self.outer.exists())
        self.assertTrue(self.checksum.exists())
        self.assertEqual(json.loads(self.index.read_text()), self.old)

    def test_preview_has_no_remote_or_local_mutations(self):
        self.args.apply = self.args.remove_local = False
        self.run_archive()
        self.assertEqual(self.bucket.uploads, [])
        self.assert_retained()

    def test_round_trip_preserves_history_and_publication_then_removes_only_staged_files(self):
        result = self.run_archive()
        self.assertFalse(result['published'])
        index = json.loads(self.index.read_text())
        self.assertEqual(index['archives'][0], self.old['archives'][0])
        self.assertEqual(json.loads(self.bucket.objects[index['remote_index_uri']]), index)
        self.assertFalse(self.outer.exists())
        self.assertFalse(self.checksum.exists())
        self.assertTrue((self.repo/'delivery/record.json').exists())
        report = json.loads((self.repo/'delivery/archive-migrations/test-archive.json').read_text())
        self.assertEqual(len(report['removed']), 2)

    def test_corrupt_download_preserves_originals_and_index(self):
        self.bucket.corrupt = 'full.zip'
        with self.assertRaisesRegex(ValueError, 'Downloaded'):
            self.run_archive()
        self.assert_retained()

    def test_index_download_failure_preserves_originals_and_index(self):
        self.bucket.fail_index = True
        with self.assertRaisesRegex(ValueError, 'index download'):
            self.run_archive()
        self.assert_retained()

    def test_changed_source_cannot_be_deleted(self):
        self.bucket.change_source = self.outer
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            self.run_archive()
        self.assert_retained()
        self.assertEqual(self.outer.read_bytes(), b'changed')

    def test_conflict_does_not_overwrite_or_delete(self):
        uri = f'{module.REMOTE}/releases/asr/android/0.3.9/{self.record["sha256"]}/full.zip'
        self.bucket.objects[uri] = b'other'
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.run_archive()
        self.assert_retained()

    def test_symlink_escape_rejected(self):
        elsewhere = self.root/'elsewhere'
        self.outer.rename(elsewhere)
        self.outer.symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_archive()
        self.assertEqual(elsewhere.read_bytes(), b'original complete delivery')

    def test_busy_file_prevents_all_deletions(self):
        with patch.object(module, 'unused', side_effect=ValueError('busy')):
            with self.assertRaisesRegex(ValueError, 'busy'):
                module.archive(self.args, self.bucket, self.repo, self.staging)
        self.assert_retained()

    def test_unpublished_record_cannot_be_promoted(self):
        self.args.publication = 'published'
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.record).encode()):
            with self.assertRaisesRegex(ValueError, 'canonical PASS'):
                self.run_archive()
        self.assert_retained()

    def test_archive_without_cleanup_keeps_local_package(self):
        self.args.remove_local = False
        self.run_archive()
        self.assertTrue(self.outer.exists())
        self.assertEqual(len(json.loads(self.index.read_text())['archives']), 2)

    def test_canonical_published_record_and_all_companions(self):
        report = self.repo/'delivery/final-report.json'
        module.write_json(report, dict(artifact=self.record['artifact'], **module.identity(self.outer)))
        self.record.update(result='PASS', published=True, acceptance_report='delivery/final-report.json',
            acceptance_sha256=module.identity(report)['sha256'],
            companions=[dict(artifact=self.checksum.name, **module.identity(self.checksum))])
        self.args.record = 'delivery/published-deliveries/release.json'
        module.write_json(self.repo/self.args.record, self.record)
        self.args.publication = 'published'
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.record).encode()):
            result = self.run_archive()
        self.assertTrue(result['published'])
        self.assertTrue(report.exists())

    def test_pass_assessment_does_not_promote_explicitly_unpublished_package(self):
        report = self.repo/'delivery/final-report.json'
        module.write_json(report, dict(artifact=self.record['artifact'], **module.identity(self.outer)))
        self.record.update(result='PASS', acceptance_report='delivery/final-report.json',
            acceptance_sha256=module.identity(report)['sha256'])
        self.args.record = 'delivery/published-deliveries/release.json'
        module.write_json(self.repo/self.args.record, self.record)
        self.args.publication = 'published'
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.record).encode()):
            with self.assertRaisesRegex(ValueError, 'publication record'):
                self.run_archive()
        self.assertEqual(self.bucket.uploads, [])
        self.assert_retained()

    def test_missing_publication_companion_blocks_before_upload(self):
        report = self.repo/'delivery/final-report.json'
        module.write_json(report, {})
        self.record.update(result='PASS', published=True, acceptance_report='delivery/final-report.json',
            acceptance_sha256=module.identity(report)['sha256'],
            companions=[dict(artifact='delivery-notes.md', size_bytes=1, sha256='a'*64)])
        self.args.record = 'delivery/published-deliveries/release.json'
        module.write_json(self.repo/self.args.record, self.record)
        self.args.publication = 'published'
        with patch.object(module.subprocess, 'check_output', return_value=json.dumps(self.record).encode()):
            with self.assertRaisesRegex(ValueError, 'companion'):
                self.run_archive()
        self.assertEqual(self.bucket.uploads, [])
        self.assert_retained()

    def test_missing_checksum_rejected_before_upload(self):
        self.checksum.unlink()
        with self.assertRaises(ValueError):
            self.run_archive()
        self.assertTrue(self.outer.exists())
        self.assertEqual(self.bucket.uploads, [])


if __name__ == '__main__':
    unittest.main()
