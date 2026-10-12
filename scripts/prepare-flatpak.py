#!/usr/bin/env python3
"""Seal wheel, metadata and media inputs for an offline Luma Flatpak build."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tomllib
import xml.etree.ElementTree as ET
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--aura-wheel', type=Path, required=True)
parser.add_argument('--numpy-wheel', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--source-commit', help='Exact Git commit for an extracted source archive')
args = parser.parse_args()
source = Path(__file__).resolve().parents[1]
version = tomllib.loads((source / 'pyproject.toml').read_text())['project']['version']
commit = args.source_commit or subprocess.check_output(
    ['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
if not re.fullmatch(r'[0-9a-f]{40}', commit):
    parser.error('source commit must be a full Git SHA')
with zipfile.ZipFile(args.aura_wheel) as archive:
    assert 'aura/app.py' in archive.namelist(), 'Not an Aura wheel'
    assert any(n.endswith('/share/applications/io.github.nmcmil.Aura.desktop') for n in archive.namelist()), 'Desktop identity missing'
    assert f'aura_wallpaper-{version}.dist-info/METADATA' in archive.namelist(), 'Wheel version differs from source'
with zipfile.ZipFile(args.numpy_wheel) as archive:
    assert 'numpy/__init__.py' in archive.namelist(), 'Not a NumPy wheel'
    assert 'cp314' in args.numpy_wheel.name and 'x86_64' in args.numpy_wheel.name, 'Requires CPython3.14 x86_64 NumPy'
args.output.mkdir(parents=True, exist_ok=False)
files = {
    'aura.whl': args.aura_wheel,
    'numpy.whl': args.numpy_wheel,
    'aura-launcher': source / 'packaging/flatpak/aura-launcher',
    'io.github.nmcmil.Aura.json': source / 'packaging/flatpak/io.github.nmcmil.Aura.json',
    'io.github.nmcmil.Aura.metainfo.xml': source / 'data/io.github.nmcmil.Aura.metainfo.xml',
    'org.project_luma.shell-state.gschema.xml': source / 'packaging/flatpak/org.project_luma.shell-state.gschema.xml',
    'luma-shell-state.LICENSE': source / 'packaging/flatpak/luma-shell-state.LICENSE',
    'aura.png': source / 'docs/images/aura.png',
}
for name, origin in files.items():
    shutil.copy2(origin, args.output / name)
screenshot = (args.output / 'aura.png').read_bytes()
assert screenshot.startswith(b'\x89PNG\r\n\x1a\n'), 'Screenshot must be PNG'
width, height = struct.unpack('>II', screenshot[16:24])
digest = hashlib.sha256(screenshot).hexdigest()
metadata = args.output / 'io.github.nmcmil.Aura.metainfo.xml'
xml = ET.fromstring(metadata.read_bytes())
assert xml.findtext('id') == 'io.github.nmcmil.Aura'
image = xml.find('./screenshots/screenshot/image')
assert image is not None, 'Screenshot declaration missing'
image.text = f'https://dl.simplyluma.com/media/io.github.nmcmil.Aura/{digest}.png'
image.set('width', str(width)); image.set('height', str(height))
metadata.write_bytes(ET.tostring(xml, encoding='utf-8', xml_declaration=True) + b'\n')
manifest_path = args.output / 'io.github.nmcmil.Aura.json'
manifest = json.loads(manifest_path.read_text())
module = manifest['modules'][0]
module['build-commands'] = [command.replace('/app/share/luma-app-media/aura.png',
    f'/app/share/luma-app-media/{digest}.png') for command in module['build-commands']]
for item in module['sources']:
    item['sha256'] = hashlib.sha256((args.output / item['path']).read_bytes()).hexdigest()
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
record = {
    'source_commit': commit, 'version': version, 'architecture': 'x86_64',
    'runtime': 'org.projectluma.Platform/x86_64/44',
    'sdk': 'org.projectluma.Sdk/x86_64/44',
    'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir()},
}
(args.output / 'build-inputs.json').write_text(json.dumps(record, indent=2) + '\n')
print(args.output)
