"""Validate student models in a HAR/HAP/AAR against the repository manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

MANIFEST = Path(__file__).resolve().parents[2] / 'shared/models/asr/dingqiao/nmnet-student/v1/manifest.json'
PREFIXES = ('resources/rawfile/', 'src/main/resources/rawfile/',
            'package/src/main/resources/rawfile/', 'assets/')
SUFFIX = 'amphion-dingqiao/nmnet-student/v1/'


def verify_archive(archive_path, manifest_path=MANIFEST):
    expected = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    is_zip = zipfile.is_zipfile(archive_path)
    archive = zipfile.ZipFile(archive_path) if is_zip else tarfile.open(archive_path)
    with archive:
        names = archive.namelist() if is_zip else archive.getnames()
        for name in names:
            if '/amphion-dingqiao/' in name and name.rsplit('/', 1)[-1].startswith(
                    ('community-', 'community1-', 'pyannote-segmentation-')):
                raise ValueError(f'Legacy diarization resource in student package: {name}')
        prefixes = [p + SUFFIX for p in PREFIXES if p + SUFFIX + 'manifest.json' in names]
        if len(prefixes) != 1:
            raise ValueError('Missing or ambiguous packaged NMNet manifest')
        prefix = prefixes[0]
        if names.count(prefix + 'manifest.json') != 1:
            raise ValueError('Duplicate packaged NMNet manifest')
        open_member = archive.open if is_zip else archive.extractfile
        with open_member(prefix + 'manifest.json') as stream:
            if json.load(stream) != expected:
                raise ValueError('Packaged NMNet manifest differs from source')
        result = {}
        for entry in expected['files']:
            member = prefix + entry['file']
            if names.count(member) != 1:
                raise ValueError(f'Missing or duplicate NMNet member: {member}')
            digest, size = hashlib.sha256(), 0
            with open_member(member) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    size += len(chunk)
                    digest.update(chunk)
            if size != entry['sizeBytes'] or digest.hexdigest() != entry['sha256']:
                raise ValueError(f'Corrupt NMNet member: {member}')
            result[entry['file']] = {'sha256': digest.hexdigest(), 'sizeBytes': size}
        for notice in ('NOTICE.md', 'ECAPA-MODEL-CARD.md', 'ECAPA-LICENSE'):
            member = prefix + notice
            if names.count(member) != 1:
                raise ValueError(f'Missing or duplicate NMNet notice: {notice}')
            with open_member(member) as stream:
                if stream.read() != (Path(manifest_path).parent / notice).read_bytes():
                    raise ValueError(f'NMNet notice differs from source: {notice}')
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_archive(args.archive), indent=2))
