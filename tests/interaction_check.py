"""Actual GTK interactions, continuous preview and background export smoke."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aura.app import Application
from aura.model import Monitor
from gi.repository import GLib, Gtk, Adw, Gdk

out=Path(os.environ.get('AURA_EVIDENCE','/tmp/aura-interaction-evidence')); out.mkdir(parents=True,exist_ok=True)
app=Application(); app.set_application_id('io.github.nmcmil.Aura.InteractionVerification')
report={}; frames=[]; errors=[]
def capture(win,name):
    paintable=Gtk.WidgetPaintable.new(win)
    win.queue_draw()
    deadline=time.monotonic()+1
    while time.monotonic()<deadline:
        context=GLib.MainContext.default()
        while context.pending(): context.iteration(False)
        snapshot=Gtk.Snapshot.new()
        paintable.snapshot(snapshot,win.get_width(),win.get_height())
        node=snapshot.to_node()
        if node is not None:
            win.get_renderer().render_texture(node,None).save_to_png(str(out/(name+'.png')))
            return
        time.sleep(.01)
    raise AssertionError(f'No rendered frame available for {name}')
def guard(fn):
    def wrapped(*args):
        try: return fn(*args)
        except Exception as e:
            import traceback; traceback.print_exc(); errors.append(str(e)); finish(); return False
    return wrapped

def close_dialogs(win):
    for d in list(win.get_dialogs()): d.close()

def finish():
    report['errors']=errors
    (out/'interactions.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report),flush=True); app.quit(); return False

@guard
def start():
    win=app.get_active_window(); win.set_default_size(1180,780)
    win.set_canvas(5120,1440); assert (win.width,win.height)==(5120,1440)
    win.numeric_change('angle',45); assert win.design.angle==45
    win.numeric_change('angle',0); assert win.controls['angle'].get_value()==0
    rgba=Gdk.RGBA(); rgba.parse('#19b8ca'); win.set_color(1,rgba)
    assert win.design.colors[1]=='#19b8ca' and win.design.palette=='Custom'
    win.save(); assert win.library.designs()
    saved_id=win.design_id; saved_count=len(win.library.designs())
    win.save()
    assert win.design_id==saved_id and len(win.library.designs())==saved_count
    report['save_and_update']='passed'
    original_finish=win.finish_preview
    def counted_finish(*args):
        frames.append(time.monotonic()); return original_finish(*args)
    win.finish_preview=counted_finish
    win.begin_gesture(); start_time=time.monotonic(); steps=[0]
    @guard
    def drag():
        steps[0]+=1; win.controls['angle'].set_value(-40+steps[0])
        if steps[0]<80: return True
        win.end_gesture(); duration=time.monotonic()-start_time
        report['live_drag']={'updates':steps[0],'frames_before_release':len(frames),'seconds':round(duration,3),'fps':round(len(frames)/duration,1)}
        assert len(frames)>10, 'Live preview did not update during continuous input'
        win.numeric_change('angle',0)
        GLib.timeout_add(800,dialogs); return False
    GLib.timeout_add(25,drag); return False

@guard
def dialogs():
    win=app.get_active_window(); capture(win,'workspace-ultrawide')
    win.show_monitors()
    def monitors():
        capture(win,'monitors'); close_dialogs(win); win.edit_colors(); GLib.timeout_add(500,colors); return False
    GLib.timeout_add(500,guard(monitors)); return False
@guard
def colors():
    win=app.get_active_window(); capture(win,'palette'); close_dialogs(win); win.show_export(); GLib.timeout_add(500,export_options); return False
@guard
def export_options():
    win=app.get_active_window(); capture(win,'export'); close_dialogs(win)
    win.run_exports([(str(out/'actual-export.png'),1024,288,None)],16)
    GLib.timeout_add(100,export_poll); return False
@guard
def export_poll():
    win=app.get_active_window()
    if win.exporting: return True
    assert (out/'actual-export.png').exists(); assert win.library.exports()
    report['background_export_and_history']='passed'; close_dialogs(win)
    win.show_library(); GLib.timeout_add(500,library); return False
@guard
def library():
    win=app.get_active_window(); capture(win,'library'); close_dialogs(win)
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    GLib.timeout_add(600,light); return False
@guard
def light():
    win=app.get_active_window(); capture(win,'light')
    settings=Gtk.Settings.get_default(); settings.set_property('gtk-enable-animations',False)
    settings.set_property('gtk-xft-dpi',int(96*1024*1.25))
    win.set_direction(Gtk.TextDirection.RTL)
    report['keyboard_save_shortcut']=app.get_accels_for_action('app.design-save')
    GLib.timeout_add(600,rtl); return False
@guard
def rtl():
    win=app.get_active_window(); capture(win,'rtl-large-text')
    report['appearance_modes']=['dark','light','RTL with 125% text and animations disabled']
    finish(); return False
app.connect('activate',lambda *_:GLib.timeout_add(1200,start))
app.run(None)
if errors: sys.exit(1)
