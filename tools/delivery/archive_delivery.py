#!/usr/bin/env python3
"""Archive an identified delivery without changing its publication status.

Defaults to a transfer preview. See delivery/PUBLISHED_ARTIFACT_ARCHIVE.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]
STAGING = Path.home() / '.cache/amphion-runtime/delivery-staging'
REMOTE = 'cos-amphion-delivery:amphion-runtime'


def identity(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Expected a regular file: {path}')
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            sha.update(chunk)
    return dict(size_bytes=path.stat().st_size, sha256=sha.hexdigest())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def relative_file(root, name):
    path = root / name
    if Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError(f'Expected a relative path: {name}')
    # Reject parent symlinks as well, so cleanup cannot escape staging.
    if path.resolve() != path.absolute() or not path.is_file():
        raise ValueError(f'Missing file or symlink: {name}')
    return path


def unused(path):
    result = subprocess.run(['lsof', str(path)], capture_output=True)
    if result.returncode != 1 or result.stderr:
        raise ValueError(f'Cannot establish that file is unused: {path}')


class Bucket:
    def __init__(self, executable):
        self.executable = executable

    def run(self, *args):
        subprocess.run([self.executable, *map(str, args)], check=True)

    def check_remote(self):
        result = subprocess.check_output([self.executable, 'remotes'], text=True)
        if not any(line.split('\t')[0] == 'cos-amphion-delivery' for line in result.splitlines()):
            raise ValueError('Required delivery bucket alias is unavailable')

    def push(self, source, uri, preview=False):
        self.run('push', source, uri, *(['--dry-run'] if preview else []))

    def pull(self, uri, destination):
        self.run('pull', uri, destination)


def archive(args, bucket, repo=REPO, staging=STAGING):
    repo, staging = repo.resolve(), staging.resolve()
    if args.remove_local and not args.apply:
        raise ValueError('--remove-local requires --apply')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', args.batch_id):
        raise ValueError('Invalid batch ID')
    record_path = relative_file(repo, args.record)
    record = json.loads(record_path.read_text())
    for key in ('platform', 'version', 'source_commit', 'artifact', 'size_bytes', 'sha256'):
        if key not in record:
            raise ValueError(f'Missing record field: {key}')
    product = record.get('product', 'asr')
    for value in (product, record['platform'], record['version']):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value):
            raise ValueError('Invalid product/platform/version')
    if not re.fullmatch(r'[0-9a-f]{40}', record['source_commit']):
        raise ValueError('Source commit must be a full SHA')
    if Path(record['artifact']).name != record['artifact']:
        raise ValueError('Artifact must be a basename')
    if args.publication == 'published':
        # The record must already exist unchanged on canonical main, not merely on this branch.
        canonical = subprocess.check_output(
            ['git', 'show', f'origin/main:{args.record}'], cwd=repo)
        if json.loads(canonical) != record or record.get('result') != 'PASS':
            raise ValueError('Published mode requires a canonical PASS publication record')
        if not args.record.startswith('delivery/published-deliveries/'):
            raise ValueError('Published mode requires an outer-package publication record')
        report = relative_file(repo, record['acceptance_report'])
        if identity(report)['sha256'] != record['acceptance_sha256']:
            raise ValueError('Acceptance report hash mismatch')
    elif record.get('published') is not False:
        raise ValueError('Unpublished mode requires explicit published: false in the record')
    stage = staging / product / record['platform'] / record['version'] / record['source_commit']
    outer = relative_file(stage, 'packages/' + record['artifact'])
    expected = {k: record[k] for k in ('size_bytes', 'sha256')}
    if identity(outer) != expected:
        raise ValueError('Outer package differs from its identity record')
    sources = [outer, record_path, relative_file(stage, 'packages/' + record['artifact'] + '.sha256')]
    checksum = sources[-1].read_text().split()
    if checksum != [record['sha256'], record['artifact']]:
        raise ValueError('External checksum does not match the outer package')
    sources += [relative_file(stage, name) for name in args.companion]
    if args.publication == 'published':
        sources.append(report)
        required = {item['artifact']: item for item in record.get('companions', [])}
        for name, item in required.items():
            matches = [p for p in sources if p.name == name]
            if len(matches) != 1 or identity(matches[0]) != {k: item[k] for k in expected}:
                raise ValueError(f'Missing/mismatched publication companion: {name}')
    if len({p.name for p in sources[1:]}) != len(sources[1:]):
        raise ValueError('Companion filenames must be unique')
    base = f'{REMOTE}/releases/{product}/{record["platform"]}/{record["version"]}/{record["sha256"]}/'
    items = [dict(artifact=p.name, **identity(p), remote_uri=base +
                  ('' if p == outer else 'companions/') + p.name) for p in sources]
    bucket.check_remote()
    for path, item in zip(sources, items):
        bucket.push(path, item['remote_uri'], preview=True)
    if not args.apply:
        return {'preview': items}
    index_path = repo / 'delivery/published-artifact-archives.json'
    # Serialize index updates and hold the lock through remote verification and cleanup.
    with (repo / 'delivery/.archive-delivery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        index_bytes = index_path.read_bytes()
        index = json.loads(index_bytes)
        migration = repo / f'delivery/archive-migrations/{args.batch_id}.json'
        if migration.exists():
            raise ValueError('Batch already recorded; choose a new batch ID')
        if any(e['remote_uri'] == items[0]['remote_uri'] for e in index['archives']):
            raise ValueError('Artifact already indexed; use the recorded URI for recovery/cleanup')
        scratch_root = stage / 'scratch'
        scratch_root.mkdir(exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='archive-', dir=scratch_root))
        try:
            for path, item in zip(sources, items):
                if identity(path) != {k: item[k] for k in expected}:
                    raise ValueError('Source changed before upload')
                bucket.push(path, item['remote_uri'])
                downloaded = tmp / item['artifact']
                bucket.pull(item['remote_uri'], downloaded)
                if identity(downloaded) != {k: item[k] for k in expected}:
                    raise ValueError('Downloaded content differs from original')
                downloaded.unlink()
                item['verification'] = dict(method='full-download-sha256',
                    verified_at=dt.datetime.now(dt.timezone.utc).isoformat(), local_copies_verified=2)
            entry = dict(product=product, platform=record['platform'], version=record['version'],
                source_commit=record['source_commit'], published=args.publication == 'published',
                identity_record=args.record, archive_basis=args.publication,
                **items[0], companions=items[1:])
            index['archives'].append(entry)
            index['batch_id'] = args.batch_id
            index['remote_index_uri'] = f'{REMOTE}/archive-index/{args.batch_id}.json'
            proposal = tmp / 'index.json'
            write_json(proposal, index)
            bucket.push(proposal, index['remote_index_uri'], preview=True)
            bucket.push(proposal, index['remote_index_uri'])
            downloaded = tmp / 'downloaded-index.json'
            bucket.pull(index['remote_index_uri'], downloaded)
            if identity(downloaded) != identity(proposal):
                raise ValueError('Remote index verification failed')
            if index_path.read_bytes() != index_bytes:
                raise ValueError('Index changed during archival; originals retained')
            # Preflight the whole deletion set before removing any original.
            for path, item in zip(sources, items):
                if identity(path) != {k: item[k] for k in expected}:
                    raise ValueError('Source changed during archival; originals retained')
                if args.remove_local and path.is_relative_to(stage):
                    unused(path)
            write_json(index_path, index)
            report_data = dict(batch_id=args.batch_id, remote_index_uri=index['remote_index_uri'],
                               status='ARCHIVED', removed=[])
            write_json(migration, report_data)
            if args.remove_local:
                for path, item in zip(sources, items):
                    if not path.is_relative_to(stage):
                        continue  # Never remove repository records or evidence.
                    if identity(path) != {k: item[k] for k in expected}:
                        raise ValueError('Source changed before deletion')
                    unused(path)
                    path.unlink()
                    report_data['removed'].append(dict(path=str(path.relative_to(staging)), **item))
                    write_json(migration, report_data)
            downloaded.unlink()
            proposal.unlink()
            # Leave any AmphionBucket recovery checkpoints intact.
            if not any(tmp.iterdir()):
                tmp.rmdir()
            return entry
        except Exception:
            print(f'Recovery files retained at {tmp}')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True, help='Repository-relative package identity JSON')
    parser.add_argument('--publication', choices=['published', 'unpublished'], required=True)
    parser.add_argument('--companion', action='append', default=[], help='File relative to the frozen staging directory; repeatable')
    parser.add_argument('--batch-id', required=True, help='Unique lowercase ID for the immutable remote index')
    parser.add_argument('--apply', action='store_true', help='Upload and verify; default only previews')
    parser.add_argument('--remove-local', action='store_true', help='Delete listed staging files only after archive verification')
    parser.add_argument('--ab', default=str(Path.home()/'.local/bin/ab'), help='AmphionBucket executable, not ApacheBench')
    args = parser.parse_args()
    try:
        result = archive(args, Bucket(args.ab))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Archive stopped: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
