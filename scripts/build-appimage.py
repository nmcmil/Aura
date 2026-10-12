#!/usr/bin/env python3
"""Seal a portable Aura directory into a single offline AppImage."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess

RUNTIME_SHA256='156f4bdbde9c52d01814600013e0a273f0118dc2de98975f3c8c63427ec79074'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--portable-dir',required=True,type=Path)
p.add_argument('--runtime',required=True,type=Path)
p.add_argument('--output',required=True,type=Path)
a=p.parse_args()
assert hashlib.sha256(a.runtime.read_bytes()).hexdigest()==RUNTIME_SHA256,'Unexpected AppImage runtime'
a.output.mkdir(parents=True,exist_ok=False)
appdir=a.output/'AppDir'
shutil.copytree(a.portable_dir,appdir)
notices=appdir/'usr/share/licenses/appimage-runtime'
notices.mkdir(parents=True,exist_ok=True)
shutil.copy2(Path(__file__).resolve().parents[1]/'packaging/portable/appimage-runtime.LICENSE',notices/'LICENSE')
(appdir/'AppRun').write_text('''#!/bin/sh
set -eu
aura_portable_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "${AURA_PORTABLE_PYTHON:-}" = 1 ]; then
 exec "$aura_portable_dir/python" "$@"
fi
exec "$aura_portable_dir/Aura" "$@"
''')
(appdir/'AppRun').chmod(0o755)
shutil.copy2(appdir/'usr/share/applications/io.github.nmcmil.Aura.desktop',appdir)
shutil.copy2(appdir/'usr/share/icons/hicolor/256x256/apps/io.github.nmcmil.Aura.png',appdir)
payload=a.output/'payload.squashfs'
subprocess.run(['mksquashfs',str(appdir),str(payload),'-noappend','-comp','zstd','-Xcompression-level','15','-processors','2'],check=True)
image=a.output/'Aura-0.1.0-x86_64.AppImage'
with image.open('wb') as out:
 for source in (a.runtime,payload):
  with source.open('rb') as inp:shutil.copyfileobj(inp,out)
image.chmod(0o755)
(a.output/'SHA256SUMS').write_text(hashlib.sha256(image.read_bytes()).hexdigest()+'  '+image.name+'\n')
print(f'{image.stat().st_size} bytes: {image}')
