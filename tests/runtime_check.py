"""Run inside a Luma Wayland session with isolated XDG data/state directories."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aura.app import Application, Window
from gi.repository import Gtk, Gio, GLib, Adw

out=Path(os.environ.get('AURA_EVIDENCE','/tmp/aura-evidence')); out.mkdir(parents=True,exist_ok=True)
app=Application(); app.set_application_id('io.github.nmcmil.Aura.Verification')
report=[]; errors=[]
widths=iter([1180,1024,500,360])

def capture(win,name):
    paintable=Gtk.WidgetPaintable.new(win)
    snapshot=Gtk.Snapshot.new()
    paintable.snapshot(snapshot,win.get_width(),win.get_height())
    node=snapshot.to_node()
    texture=win.get_renderer().render_texture(node,None)
    texture.save_to_png(str(out/f'{name}.png'))

def next_width():
    win=app.get_active_window()
    try: width=next(widths)
    except StopIteration:
        print(json.dumps(report),flush=True)
        (out/'runtime.json').write_text(json.dumps(report,indent=2)); app.quit(); return False
    win.set_default_size(width,760)
    def check():
        try:
            capture(win,f'window-{width}')
            report.append({'requested_width':width,'actual_width':win.get_width(),'collapsed':win.compact,'preview':win.picture.get_paintable() is not None})
            assert win.get_width() == width, 'Window did not reach the requested width'
            assert win.picture.get_paintable() is not None, 'Preview was not rendered'
            assert win.compact == (width <= 500), 'Unexpected responsive layout'
            if width<=500:
                win.show_editor(True)
                def inspector():
                    capture(win,f'inspector-{width}'); win.show_editor(False); GLib.timeout_add(400,next_width); return False
                GLib.timeout_add(600,inspector)
            else: GLib.timeout_add(200,next_width)
        except Exception as e:
            import traceback; traceback.print_exc(); errors.append(str(e)); app.quit()
        return False
    GLib.timeout_add(1300,check); return False

def ready(*_): GLib.timeout_add(2000,next_width)
app.connect('activate',ready)
app.run(None)
if errors: sys.exit(1)
