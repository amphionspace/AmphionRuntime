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


def build(aar, model, android_root, output, version):
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        raise ValueError('Invalid delivery version')
    name = f'lits-dingqiao-tts-android-sdk-vocos24k-{version}'
    if output.name != name or output.resolve() in (model.resolve(), android_root.resolve()):
        raise ValueError('Output must be a dedicated versioned delivery directory')
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
    with zipfile.ZipFile(aar) as z:
        if z.testzip() or 'classes.jar' not in z.namelist():
            raise ValueError('Invalid AAR')
        if any(n.lower().endswith(('.lic', '.pem', '.p12', '.jks')) for n in z.namelist()):
            raise ValueError('Authorization/signing material inside AAR')
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copy2(aar, output / f'lits-dingqiao-tts-sdk-vocos24k-{version}.aar')
    resources = output / 'external-resources' / 'tts' / model_id / model_version
    resources.mkdir(parents=True)
    for filename in sorted(names):
        dest = resources / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model / filename, dest)
    manifest['files'] = [{'name': n, 'size_bytes': (resources / n).stat().st_size} for n in sorted(names)]
    (resources / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
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
    for arg in ('aar', 'model-dir', 'android-root', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    print(build(args.aar, args.model_dir, args.android_root, args.output, args.version))
