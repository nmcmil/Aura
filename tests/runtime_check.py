"""Native rendered layout gates; run with disposable XDG data/state."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aura.app import Application
from gi.repository import Gtk, GLib

out=Path(os.environ.get('AURA_EVIDENCE','/tmp/aura-evidence')); out.mkdir(parents=True,exist_ok=True)
app=Application(); app.set_application_id('io.github.nmcmil.Aura.Verification')
report=[]; errors=[]
widths=iter([1880,1180,1024,500,360])


def capture(win,name):
    snapshot=Gtk.Snapshot.new()
    Gtk.WidgetPaintable.new(win).snapshot(snapshot,win.get_width(),win.get_height())
    node=snapshot.to_node()
    assert node is not None,'No rendered GTK frame'
    win.get_renderer().render_texture(node,None).save_to_png(str(out/f'{name}.png'))


def fit(win,width,height=760):
    # GTK's configured surface includes the toolkit's external shadow; test usable widget width.
    surface=win.get_surface()
    dx=surface.get_width()-win.get_width(); dy=surface.get_height()-win.get_height()
    win.set_default_size(width+dx,height+dy)


def guard(fn):
    def run():
        try: return fn()
        except Exception as e:
            import traceback; traceback.print_exc(); errors.append(str(e)); app.quit(); return False
    return run


@guard
def next_width():
    win=app.get_active_window(); win.action_center.fold_panel()
    try: width=next(widths)
    except StopIteration:
        GLib.timeout_add(300,short_window); return False
    fit(win,width)
    @guard
    def check():
        capture(win,f'window-{width}')
        assert win.get_width()==width, f'Requested usable width {width}, got {win.get_width()}'
        assert win.picture.get_paintable() is not None
        assert win.compact==(width<=500)
        assert win.workspace.__gtype__.name=='LumaCreativeWorkspace'
        assert win.creation.__gtype__.name=='LumaFloatingPanel'
        panels=iter(['style','colors','adjust','size','size-presets','custom-colors','batch','monitors','export'])
        record={'requested_width':width,'actual_width':win.get_width(),'preview':True,'panels':[]}
        report.append(record)
        @guard
        def next_panel():
            win.action_center.fold_panel()
            try: key=next(panels)
            except StopIteration:
                GLib.timeout_add(200,next_width); return False
            if key=='size-presets': win.show_size_presets()
            elif key=='custom-colors': win.edit_colors()
            elif key=='batch': win.show_batch()
            elif key=='monitors': win.show_monitors()
            elif key=='export': win.show_export()
            else: win.open_panel(key)
            @guard
            def inspect():
                capture(win,f'{key}-{width}')
                assert win.picture.get_visible() and win.picture.get_height()>60,'Live preview lost while editing'
                if win.action_center.get_visible():
                    assert win.action_center.get_width()<=win.host.get_width(),'Bar clips beyond its host'
                if key in ('style','colors','adjust','custom-colors'):
                    assert win.creation.get_visible() and win.creation_pages[win.creation.get_page()].get_first_child() is not None
                    assert win.action_center.grown is None
                else: assert win.action_center.panel.get_child() is not None
                if win.action_center.get_visible():
                    ok,bounds=win.action_center.bar.compute_bounds(win.host)
                    assert ok and bounds.get_y()+bounds.get_height()<=win.host.get_height()-16,'Bottom bar clearance lost'
                if win.compact and win.creation.get_folded() and win.document_title.get_visible():
                    ok,panel_bounds=win.creation.compute_bounds(win.host)
                    title_ok,title_bounds=win.document_title.compute_bounds(win.host)
                    assert ok and title_ok and title_bounds.get_y()>=panel_bounds.get_y()+panel_bounds.get_height(),'Document title overlaps folded creation header'
                if not win.compact:
                    from luma_appkit.lumaui_tokens import CREATIVE
                    assert win.creation.get_width()<=CREATIVE['panel_left_width']+2*CREATIVE['panel_inset']
                record['panels'].append({'name':key,'preview_height':win.picture.get_height(),'bar_width':win.action_center.get_width()})
                GLib.timeout_add(80,next_panel); return False
            GLib.timeout_add(550,inspect); return False
        next_panel(); return False
    GLib.timeout_add(800,check); return False


@guard
def short_window():
    win=app.get_active_window(); fit(win,360,420)
    win.open_panel('adjust')
    @guard
    def check_short():
        capture(win,'adjust-360-short')
        assert win.short and win.compact and win.get_width()==360 and win.picture.get_height()>60
        if win.action_center.get_visible(): assert win.action_center.get_width()<=win.host.get_width()
        report.append({'width':win.get_width(),'height':win.get_height(),'preview_height':win.picture.get_height(),'short':True})
        (out/'runtime.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report),flush=True)
        app.quit(); return False
    GLib.timeout_add(750,check_short); return False

app.connect('activate',lambda *_:GLib.timeout_add(1200,next_width))
app.run(None)
if errors: sys.exit(1)
