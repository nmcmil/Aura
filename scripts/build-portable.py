#!/usr/bin/env python3
"""Build portable Aura without downloading dependencies or changing its data paths."""
from pathlib import Path
import os,json,shutil,subprocess,tarfile,base64,xml.etree.ElementTree as ET,hashlib
import argparse,re
parser=argparse.ArgumentParser(description='Build a minimal relocatable Aura directory from a qualified Luma runtime and built application.')
parser.add_argument('--runtime-files',required=True,type=Path)
parser.add_argument('--app-files',required=True,type=Path)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
root=args.runtime_files.resolve();app=args.app_files.resolve();out=args.output.resolve()
out.mkdir(parents=True,exist_ok=False);dest=out/'Aura';dest.mkdir()
assert (app/'lib/python3.14/site-packages/aura_wallpaper-0.1.0.dist-info').is_dir()
assert (root/'lib/python3.14/site-packages/luma_appkit').is_dir()
# Discover actual ELF dependencies, including NumPy's separately bundled libraries.
libs={p.name:p for p in (root/'lib64').glob('*.so*')}
for p in (app/'lib/python3.14/site-packages/numpy.libs').glob('*.so*'):libs[p.name]=p
seeds=[root/'bin/python3']
for pattern in ('libgtk-4.so.*','libadwaita-1.so.*','libluma*.so.*','libgirepository*.so.*','libgdk_pixbuf*.so.*','libcairo*.so.*','librsvg*.so.*'):
 seeds.extend((root/'lib64').glob(pattern))
seeds.extend((root/'lib64/python3.14/lib-dynload').glob('*.so'))
for pkg in ('gi','cairo'):seeds.extend((root/'lib64/python3.14/site-packages'/pkg).rglob('*.so'))
seeds.extend((app/'lib/python3.14/site-packages').rglob('*.so'))
seeds.extend((app/'lib/python3.14/site-packages/numpy.libs').glob('*.so*'))
seen=set();missing=set();queue=list(seeds)
while queue:
 p=queue.pop().resolve()
 if p in seen:continue
 seen.add(p)
 result=subprocess.run(['readelf','-d',str(p)],capture_output=True,text=True,check=True)
 for name in re.findall(r'Shared library: \[(.*?)\]',result.stdout):
  if name in libs:queue.append(libs[name])
  else:missing.add(name)
if missing:raise RuntimeError('Missing native dependencies: '+', '.join(sorted(missing)))
paths=sorted(str(p.relative_to(root)) for p in seen if p.is_relative_to(root))
(out/'dependencies.json').write_text(json.dumps({'runtime_files':str(root),'app_files':str(app),'native_paths':paths},indent=2))
def copy(p,relative=None):
 q=dest/(relative or p.relative_to(root));q.parent.mkdir(parents=True,exist_ok=True)
 if p.is_dir():shutil.copytree(p,q,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 else:shutil.copy2(p,q)
resolved={str((root/p).resolve()) for p in paths}
for p in paths:copy(root/p,Path('usr')/p)
for p in (root/'lib64').glob('*.so*'):
 if p.is_symlink() and str(p.resolve()) in resolved:
  target=dest/'usr/lib64'/p.name
  if not target.exists():target.symlink_to(p.resolve().name)
for name in ('libpthread.so.0','libdl.so.2','libgcc_s.so.1'):
 copy(root/'lib64'/name,Path('usr/lib64')/name)
copy(root/'lib64/ld-linux-x86-64.so.2','usr/lib64/ld-linux-x86-64.so.2')
copy(root/'lib64/python3.14','usr/lib64/python3.14')
site=dest/'usr/lib64/python3.14/site-packages'
for p in list(site.iterdir()):
 if p.name not in ('gi','cairo','luma_appkit') and not p.name.startswith(('PyGObject-','pycairo-')):
  shutil.rmtree(p) if p.is_dir() else p.unlink()
shutil.copytree(root/'lib/python3.14/site-packages/luma_appkit',site/'luma_appkit',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copytree(app/'lib/python3.14/site-packages',site,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
# Relocatable AppKit lookup uses sheets alongside the installed Python package.
for p in (root/'share/luma-appkit').glob('*.css'):shutil.copy2(p,site/p.name)
for relative in ('share/glib-2.0/schemas','share/icons/Prairie','share/icons/Adwaita','share/icons/hicolor','share/fonts/google-figtree-fonts','share/licenses'):
 copy(root/relative,Path('usr')/relative)
shutil.copytree(app/'share',dest/'usr/share',dirs_exist_ok=True)
icon=dest/'usr/share/icons/hicolor/scalable/apps/io.github.nmcmil.Aura.svg'
raw=base64.b64decode(ET.parse(icon).getroot()[0].attrib['{http://www.w3.org/1999/xlink}href'].split(',',1)[1])
assert hashlib.sha256(raw).hexdigest()=='948fa1837bbefae5d814183e5cb76212a7a6d6a2930bb5b2f33238a5ece3a911'
png=dest/'usr/share/icons/hicolor/256x256/apps/io.github.nmcmil.Aura.png';png.parent.mkdir(parents=True,exist_ok=True);png.write_bytes(raw);icon.unlink()
# Introspection namespaces used by GTK, cairo, AppKit and their dependencies.
for name in ('Gtk-4.0','Gdk-4.0','Gsk-4.0','Adw-1','LumaUI-1','LumaSemantics-1','LumaAppearance-1','GLib-2.0','GObject-2.0','Gio-2.0','GModule-2.0','GLibUnix-2.0','GioUnix-2.0','GdkPixbuf-2.0','Pango-1.0','PangoCairo-1.0','PangoFT2-1.0','Graphene-1.0','cairo-1.0','freetype2-2.0','HarfBuzz-0.0','GdkX11-4.0','GdkWayland-4.0','xlib-2.0'):
 p=root/'lib64/girepository-1.0'/f'{name}.typelib'
 if p.exists():copy(p,Path('usr')/p.relative_to(root))
(dest/'fonts.conf').write_text('<fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir prefix="relative">usr/share/fonts</dir><cachedir prefix="xdg">fontconfig</cachedir></fontconfig>')
launcher='''#!/bin/sh
set -eu
aura_portable_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONHOME="$aura_portable_dir/usr"
export PYTHONPATH="$aura_portable_dir/usr/lib64/python3.14/site-packages"
export GI_TYPELIB_PATH="$aura_portable_dir/usr/lib64/girepository-1.0"
export XDG_DATA_DIRS="$aura_portable_dir/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
export FONTCONFIG_FILE="$aura_portable_dir/fonts.conf"
export GSETTINGS_SCHEMA_DIR="$aura_portable_dir/usr/share/glib-2.0/schemas"
exec "$aura_portable_dir/usr/lib64/ld-linux-x86-64.so.2" --inhibit-cache --library-path "$aura_portable_dir/usr/lib64:$aura_portable_dir/usr/lib64/python3.14/site-packages/numpy.libs" "$aura_portable_dir/usr/bin/python3.14" "$@"
'''
(dest/'python').write_text(launcher);(dest/'python').chmod(0o755)
(dest/'Aura').write_text('#!/bin/sh\nset -eu\naura_portable_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$aura_portable_dir/python" -m aura "$@"\n');(dest/'Aura').chmod(0o755)
with tarfile.open(out/'Aura-0.1.0-x86_64-portable.tar.gz','w:gz',compresslevel=6) as t:t.add(dest,arcname='Aura')
print(json.dumps({'uncompressed_bytes':sum(p.stat().st_size for p in dest.rglob('*') if p.is_file() and not p.is_symlink()),'archive_bytes':(out/'Aura-0.1.0-x86_64-portable.tar.gz').stat().st_size}))
subprocess.run([str(dest/'python'),'-c','import aura,numpy,gi;from aura.app import Application;print(aura.__file__,numpy.__version__,Application)'],check=True,cwd=out)
