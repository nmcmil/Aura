#!/usr/bin/env python3
"""Seal already-built wheels for an offline Luma Flatpak build."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--aura-wheel',type=Path,required=True)
parser.add_argument('--numpy-wheel',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
source=Path(__file__).resolve().parents[1]
with zipfile.ZipFile(args.aura_wheel) as archive:
    assert 'aura/app.py' in archive.namelist(), 'Not an Aura wheel'
    assert any(n.endswith('/share/applications/io.github.nmcmil.Aura.desktop') for n in archive.namelist()), 'Desktop identity missing'
with zipfile.ZipFile(args.numpy_wheel) as archive:
    assert 'numpy/__init__.py' in archive.namelist(), 'Not a NumPy wheel'
    assert 'cp314' in args.numpy_wheel.name and 'x86_64' in args.numpy_wheel.name, 'Requires CPython3.14 x86_64 NumPy'
args.output.mkdir(parents=True,exist_ok=False)
for src,name in ((args.aura_wheel,'aura.whl'),(args.numpy_wheel,'numpy.whl'),
                 (source/'packaging/flatpak/aura-launcher','aura-launcher'),
                 (source/'packaging/flatpak/io.github.nmcmil.Aura.json','io.github.nmcmil.Aura.json')):
    shutil.copy2(src,args.output/name)
manifest=json.loads((args.output/'io.github.nmcmil.Aura.json').read_text())
for item in manifest['modules'][0]['sources']:
    item['sha256']=hashlib.sha256((args.output/item['path']).read_bytes()).hexdigest()
(args.output/'io.github.nmcmil.Aura.json').write_text(json.dumps(manifest,indent=2)+'\n')
record={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),
        'version':'0.1.0','architecture':'x86_64','runtime':'org.projectluma.Platform/x86_64/44',
        'sdk':'org.projectluma.Sdk/x86_64/44','files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir()}}
(args.output/'build-inputs.json').write_text(json.dumps(record,indent=2)+'\n')
print(args.output)
