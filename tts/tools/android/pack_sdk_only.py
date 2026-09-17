#!/usr/bin/env python3
"""Package the documented Android SDK-only layout from a frozen AAR and model."""
import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_manifest(model):
    manifest = json.loads((model / 'manifest.json').read_text())
    model_id = manifest['model_id']
    model_version = manifest['version']
    for segment in (model_id, model_version):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', segment) or segment in ('.', '..'):
            raise ValueError('Invalid model directory segment')
    names = {x['name'] for x in manifest['files']}
    # Runtime explicitly requires frontend_golden.json; export_report is offline evidence only.
    names.discard('export_report.json')
    names.add('frontend_golden.json')
    names.discard('manifest.json')
    for name_in_model in names:
        p = Path(name_in_model)
        if p.is_absolute() or '..' in p.parts or p.suffix not in ('.json', '.txt', '.bin', '.onnx'):
            raise ValueError(f'Unexpected resource: {p}')
        if not (model / p).is_file() or (model / p).is_symlink():
            raise ValueError(f'Missing or linked resource: {p}')
    manifest['files'] = [{'name': n, 'size_bytes': (model / n).stat().st_size, 'sha256': sha256(model / n)} for n in sorted(names)]
    return manifest, names


def stage_assets(model, output):
    manifest, names = runtime_manifest(model)
    if output.resolve() == model.resolve() or output.resolve() in model.resolve().parents or model.resolve() in output.resolve().parents:
        raise ValueError('Asset staging must be separate from the source model')
    if output.exists():
        shutil.rmtree(output)
    resources = output / 'lits-models' / 'tts' / manifest['model_id'] / manifest['version']
    resources.mkdir(parents=True)
    for name in sorted(names):
        dest = resources / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model / name, dest)
    (resources / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


def build(aar, model, android_root, output, version):
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('Invalid delivery version')
    name = f'lits-dingqiao-tts-android-sdk-vocos24k-{version}'
    if output.name != name or output.resolve() in (model.resolve(), android_root.resolve()):
        raise ValueError('Output must be a dedicated versioned delivery directory')
    manifest, names = runtime_manifest(model)
    model_id, model_version = manifest['model_id'], manifest['version']
    with zipfile.ZipFile(aar) as z:
        if z.testzip() or 'classes.jar' not in z.namelist():
            raise ValueError('Invalid AAR')
        if any(n.lower().endswith(('.lic', '.pem', '.p12', '.jks')) for n in z.namelist()):
            raise ValueError('Authorization/signing material inside AAR')
        prefix = f'assets/lits-models/tts/{model_id}/{model_version}/'
        if any(n.startswith('assets/lits-models/tts/') and not n.startswith(prefix) and not n.endswith('/') for n in z.namelist()):
            raise ValueError('Unexpected additional model inside AAR')
        expected = {'manifest.json', *names}
        actual = {n.removeprefix(prefix) for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')}
        if actual != expected:
            raise ValueError('AAR bundled resource list does not match model')
        if json.loads(z.read(prefix + 'manifest.json')) != manifest:
            raise ValueError('AAR bundled manifest does not match model')
        for entry in manifest['files']:
            if hashlib.sha256(z.read(prefix + entry['name'])).hexdigest() != entry['sha256']:
                raise ValueError('AAR bundled resource hash mismatch: ' + entry['name'])
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copy2(aar, output / f'lits-dingqiao-tts-sdk-vocos24k-{version}.aar')
    for filename in ('LICENSE', 'NOTICE'):
        shutil.copy2(android_root / filename, output / filename)
    shutil.copy2(android_root / 'docs/SDK_README.md', output / 'README.md')
    changelog = (android_root / 'CHANGELOG.md').read_text()
    section = re.search(r'(?ms)^## \[' + re.escape(version) + r'\].*?(?=^## \[|\Z)', changelog)
    if section is None:
        raise ValueError('Current version missing from CHANGELOG')
    # Internal release ledger is for maintainers, not a customer dependency.
    lines = [line for line in section[0].splitlines() if 'docs/releases/' not in line]
    (output / 'CHANGELOG.md').write_text('# Changelog\n\n' + '\n'.join(lines).strip() + '\n')
    (output / 'docs').mkdir()
    for filename in ('API.md', 'INTEGRATION.md', 'PSEUDOCODE.md'):
        shutil.copy2(android_root / 'docs' / filename, output / 'docs' / filename)
    for p in output.rglob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
            if '://' not in target and not target.startswith('#') and not (p.parent / target.split('#')[0]).exists():
                raise ValueError(f'Broken documentation link in {p.name}: {target}')
    files = sorted(p for p in output.rglob('*') if p.is_file())
    (output / 'CHECKSUMS.txt').write_text(''.join(f'{sha256(p)}  {p.relative_to(output).as_posix()}\n' for p in files))
    archive = output.parent / (output.name + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(output.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(output.parent))
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError('Archive CRC failed')
        for line in (output / 'CHECKSUMS.txt').read_text().splitlines():
            digest, filename = line.split('  ', 1)
            if hashlib.sha256(z.read(output.name + '/' + filename)).hexdigest() != digest:
                raise ValueError(f'Archive hash mismatch: {filename}')
    archive.with_suffix('.zip.sha256').write_text(f'{sha256(archive)}  {archive.name}\n')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-assets', action='store_true')
    parser.add_argument('--aar', type=Path)
    parser.add_argument('--android-root', type=Path)
    for arg in ('model-dir', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--version')
    args = parser.parse_args()
    if args.stage_assets:
        stage_assets(args.model_dir, args.output)
    else:
        if not all((args.aar, args.android_root, args.version)):
            parser.error('--aar, --android-root and --version are required for packaging')
        print(build(args.aar, args.model_dir, args.android_root, args.output, args.version))
