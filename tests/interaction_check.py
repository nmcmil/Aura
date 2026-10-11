"""Real native controls, live preview, legacy-compatible persistence and background export."""
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aura.app import Application
from aura.model import EFFECTS, PALETTES, Design
from gi.repository import GLib, Gtk, Adw, Gdk, Gio

out=Path(os.environ.get('AURA_EVIDENCE','/tmp/aura-interactions')); out.mkdir(parents=True,exist_ok=True)
app=Application(); app.set_application_id('io.github.nmcmil.Aura.InteractionVerification')
report={}; frames=[]; errors=[]


def panel_row(win,label):
    from luma_appkit import PanelRow, TextButton
    def descendants(widget):
        yield widget
        child=widget.get_first_child()
        while child:
            yield from descendants(child)
            child=child.get_next_sibling()
    return next(widget for widget in descendants(win.action_center.panel)
                if (isinstance(widget,PanelRow) and widget.label==label) or
                   (isinstance(widget,TextButton) and widget.label_widget.get_text()==label))


def descendants(widget):
    yield widget
    child=widget.get_first_child()
    while child:
        yield from descendants(child); child=child.get_next_sibling()

def number_entry(field):
    return next(w for w in descendants(field) if isinstance(w,(Gtk.Entry,Gtk.Text)))

def number_key(field,key):
    for widget in descendants(field):
        controllers=widget.observe_controllers()
        for i in range(controllers.get_n_items()):
            controller=controllers.get_item(i)
            if isinstance(controller,Gtk.EventControllerKey):
                if controller.emit('key-pressed',key,0,Gdk.ModifierType(0)): return
    raise AssertionError('Native numeric keyboard controller did not handle input')


def capture(win,name):
    win.queue_draw(); deadline=time.monotonic()+1
    while time.monotonic()<deadline:
        context=GLib.MainContext.default()
        while context.pending(): context.iteration(False)
        snapshot=Gtk.Snapshot.new()
        Gtk.WidgetPaintable.new(win).snapshot(snapshot,win.get_width(),win.get_height())
        node=snapshot.to_node()
        if node is not None:
            win.get_renderer().render_texture(node,None).save_to_png(str(out/f'{name}.png'))
            return
        time.sleep(.01)
    raise AssertionError('No rendered GTK frame for '+name)


def finish():
    report['errors']=errors
    (out/'interactions.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report),flush=True)
    app.quit(); return False


def guard(fn):
    def wrapped(*args):
        try: return fn(*args)
        except Exception as e:
            import traceback; traceback.print_exc(); errors.append(str(e)); return finish()
    return wrapped


def later(callback,ms=450): GLib.timeout_add(ms,guard(callback))


@guard
def start():
    win=app.get_active_window()
    win.open_panel('style')
    for effect in EFFECTS:
        # Exercise the native media tile activation and selected state.
        win.choice_buttons[effect].on_activate()
        assert win.design.effect==effect and win.choice_buttons[effect].selected
    assert len(win.choice_buttons)==7
    report['visual_style_choices']='passed'
    win.action_center.fold_panel(); win.open_panel('colors')
    win.palette_tiles['Meadow'].on_activate()
    assert win.design.colors==PALETTES['Meadow'] and win.design.palette=='Meadow'
    win.edit_colors(); later(colors); return False


@guard
def colors():
    win=app.get_active_window()
    win.color_swatches[1].emit('clicked')
    rgba=Gdk.RGBA(); rgba.parse('#19b8ca')
    win.color_well.set_rgba(rgba)
    assert win.design.colors[1]=='#19b8ca' and win.design.palette=='Custom'
    win.reverse_palette(); assert win.design.colors[-2]=='#19b8ca'
    win.undo(); assert win.design.colors[1]=='#19b8ca'
    report['palette_custom_color_reverse_undo']='passed'
    capture(win,'custom-colors')
    win.action_center.fold_panel(); win.open_panel('adjust')
    win.open_panel('size')
    win.canvas_width.entry.set_text('2560 * 2'); win.canvas_height.entry.set_text('1440')
    win.apply_dimensions()
    assert (win.width,win.height)==(5120,1440)
    win.open_panel('adjust')
    assert win.creation.get_visible() and win.action_center.grown is None
    report['sidebar_and_custom_dimensions']='passed'
    win.numeric_change('angle',45); assert win.design.angle==45
    win.numeric_change('angle',0); assert win.controls['angle'].value==0
    win.save(); saved_id=win.design_id; saved_count=len(win.library.designs())
    app.activate_action('design-save',None)
    assert win.design_id==saved_id and len(win.library.designs())==saved_count
    assert app.get_accels_for_action('app.design-save')
    report['save_shortcut_and_update']='passed'
    original_finish=win.finish_preview
    def counted_finish(*args):
        frames.append(time.monotonic()); return original_finish(*args)
    win.finish_preview=counted_finish
    later(slider_drag); return False


@guard
def slider_drag():
    win=app.get_active_window()
    drag_controller=next(controller for widget in descendants(win.controls['angle'])
        for controller in [widget.observe_controllers().get_item(i) for i in range(widget.observe_controllers().get_n_items())]
        if isinstance(controller,Gtk.GestureDrag))
    undo_before=len(win.undo_stack)
    assert win.controls['angle'].__gtype__.name=='LumaUIValueSlider'
    # Synthetic gesture origin is zero; start at the native range's current thumb.
    slider_range=win.controls['angle'].range
    from luma_appkit.media_adjust import A
    usable=slider_range.get_width()-A['thumb']
    assert usable>50,'Slider must be allocated before pointer input'
    start_x=A['thumb']/2+(slider_range.value-slider_range.minimum)/(slider_range.maximum-slider_range.minimum)*usable
    drag_controller.emit('drag-begin',float(start_x),0.0)
    start_time=time.monotonic(); steps=[0]
    @guard
    def drag():
        steps[0]+=1; drag_controller.emit('drag-update',float(start_x+usable*.4*steps[0]/80),0.0)
        if steps[0]<80:return True
        drag_controller.emit('drag-end',float(start_x+usable*.4),0.0)
        assert len(win.undo_stack)==undo_before+1 and not win.gesture_active,'Native scrub must be one undo step'
        duration=time.monotonic()-start_time
        report['live_drag']={'updates':steps[0],'frames_before_release':len(frames),'seconds':round(duration,3)}
        assert len(frames)>10,'Preview starved during continuous input'
        later(position); return False
    GLib.timeout_add(25,drag); return False


@guard
def position():
    win=app.get_active_window(); before=win.design.to_dict(); undo_count=len(win.undo_stack)
    # Emit the actual pointer gesture over the rendered image's center.
    ox,oy,w,h=win.zoom_preview.fit_rect
    x,y=ox+w/2+10,oy+h/2
    win.position_drag.emit('drag-begin',x,y)
    assert win.design.to_dict()==before,'Grabbing the preview must not jump its pattern'
    win.position_drag.emit('drag-update',24.0,12.0)
    win.position_drag.emit('drag-end',24.0,12.0)
    assert len(win.undo_stack)==undo_count+1
    assert win.design.center_x>.5 and win.design.center_y>.5
    app.activate_action('design-undo',None); assert win.design.to_dict()==before
    app.activate_action('design-redo',None); assert win.design.center_x>.5
    report['pointer_position_and_keyboard_undo_redo']='passed'
    later(export_options)


@guard
def export_options():
    win=app.get_active_window(); capture(win,'finish-adjustments')
    win.show_export(); later(export_start)


@guard
def export_start():
    win=app.get_active_window(); capture(win,'export-options')
    win.run_exports([(str(out/'actual-export.png'),1024,288,None)],16)
    later(export_finished,100)


@guard
def export_finished():
    win=app.get_active_window()
    if win.exporting: later(export_finished,100); return False
    assert (out/'actual-export.png').exists() and win.library.exports()
    report['background_export_and_history']='passed'
    # Exercise cancellation through the actual progress panel before any replacement.
    win.cancel_target=out/'cancelled.png'; win.cancel_target.write_bytes(b'previous wallpaper')
    win.run_exports([(str(win.cancel_target),2048,2048,None)],16)
    assert win.close_requested() is True,'Closing must preserve the active export'
    panel_row(win,'Cancel export').emit('clicked')
    later(cancelled,100)


@guard
def cancelled():
    win=app.get_active_window()
    if win.exporting: later(cancelled,100); return False
    assert win.cancel_target.read_bytes()==b'previous wallpaper'
    assert not list(out.glob('.aura-*.part'))
    report['cancel_preserves_destination']='passed'
    win.show_library(); later(library)


@guard
def library():
    win=app.get_active_window(); capture(win,'saved-designs')
    stored_id,stored,_=win.library.designs()[0]
    panel_row(win,stored.name or 'Untitled').emit('clicked')
    assert win.design_id==stored_id and win.design.to_dict()==stored.to_dict()
    assert not win.undo_stack,'Undo history crossed a saved-document boundary'
    app.activate_action('design-save',None)
    assert len(win.library.designs())==1
    report['library_open_document_boundary']='passed'
    win.action_center.fold_panel(); later(size_stability)


@guard
def size_stability():
    win=app.get_active_window()
    win.before_size=(win.picture.get_width(),win.picture.get_height())
    win.bar_anchor('size').emit('clicked'); later(zoom)


@guard
def zoom():
    win=app.get_active_window()
    assert (win.picture.get_width(),win.picture.get_height())==win.before_size,'Size resized the wallpaper'
    assert abs(win.canvas_width.get_width()-win.canvas_height.get_width())<=1
    assert win.canvas_width.label.get_text()=='Width'
    before=win.design.to_dict(); dimensions=(win.width,win.height); revision=win.revision
    app.activate_action('view-zoom-in',None); assert win.zoom_preview.zoom==1.25
    capture(win,'wallpaper-zoom-125')
    app.activate_action('view-zoom-out',None); assert win.zoom_preview.zoom==1
    app.activate_action('view-zoom-in',None); app.activate_action('view-zoom-reset',None)
    assert win.zoom_preview.zoom==1
    class Wheel:
        def get_current_event_state(self): return Gdk.ModifierType.CONTROL_MASK
    assert win.scroll_zoom(Wheel(),0,-1) and win.zoom_preview.zoom==1.25
    win.set_zoom(1)
    assert win.design.to_dict()==before and (win.width,win.height)==dimensions and win.revision==revision
    assert win.bar_anchor('size').bar_words.get_text()==f'{win.width:,} × {win.height:,}'
    report['size_stable_side_by_side_zoom_pixels_only']='passed'
    win.action_center.fold_panel()
    previous=win.picture.get_paintable()
    win.picture.set_paintable(Gdk.MemoryTexture.new(160,90,Gdk.MemoryFormat.R8G8B8,
        GLib.Bytes.new(bytes((239,89,34))*160*90),160*3))
    win.creation.set_visible(False); win.action_center.set_visible(False); win.set_zoom(8)
    capture(win,'zoom-full-workspace-rounded-corners')
    from gi.repository import GdkPixbuf
    pixbuf=GdkPixbuf.Pixbuf.new_from_file(str(out/'zoom-full-workspace-rounded-corners.png'))
    data=pixbuf.get_pixels(); stride=pixbuf.get_rowstride(); channels=pixbuf.get_n_channels()
    def orange(x,y):
        at=round(y)*stride+round(x)*channels
        r,g,b=data[at:at+3]; return r>180 and 40<g<160 and b<100
    ok,area=win.host.compute_bounds(win); assert ok
    x,y,w,h=area.get_x(),area.get_y(),area.get_width(),area.get_height()
    # The toolkit's inset rim shades several edge pixels. Find the painted
    # extent and permit only that rim, not Aura's former 24/92/264px gaps.
    horizontal=[px for px in range(round(x),round(x+w)) if orange(px,y+h/2)]
    vertical=[py for py in range(round(y),round(y+h)) if orange(x+w/2,py)]
    assert horizontal and vertical
    left,right=horizontal[0],horizontal[-1]; top,bottom=vertical[0],vertical[-1]
    assert max(left-x,x+w-1-right,top-y,y+h-1-bottom)<=8,'Zoom stopped before the native rim'
    for px,py in ((left+1,top+1),(right-1,top+1),(left+1,bottom-1),(right-1,bottom-1)):
        assert not orange(px,py),f'Native inner corner failed to clip: {px},{py}'
    report['zoom_reaches_all_edges_native_four_corner_clip']='passed'
    win.picture.set_paintable(previous); win.set_zoom(1)
    win.creation.set_visible(True); win.action_center.set_visible(True)
    win.show_monitors(); later(monitors)


@guard
def monitors():
    win=app.get_active_window()
    assert win.canvas_stack.get_visible_child() is win.monitor_canvas
    capture(win,'monitor-main-canvas-before-add')
    assert win.monitor_canvas.get_width()>500 and win.monitor_canvas.get_height()>200,(win.get_width(),win.get_height(),win.monitor_canvas.get_width(),win.monitor_canvas.get_height())
    assert not win.monitor_canvas.is_ancestor(win.action_center.panel)
    panel_row(win,'Add display').emit('clicked')
    assert len(win.monitors)==2
    later(monitor_dragging); return False


@guard
def monitor_dragging():
    win=app.get_active_window()
    w,h=win.monitor_canvas.get_width(),win.monitor_canvas.get_height()
    scale=min((w-32)/5120,(h-32)/1440)
    left=(w-5120*scale)/2; top=(h-1440*scale)/2
    win.monitor_drag.emit('drag-begin',left+1280*scale,top+720*scale)
    win.monitor_drag.emit('drag-update',0.,-100*scale)
    win.monitor_drag.emit('drag-end',0.,-100*scale)
    assert win.monitors[0].y==-100,'Dragging on the main canvas failed'
    assert win.monitor_fields[(id(win.monitors[0]),'y')].get_value()==-100
    win.monitor_fields[(id(win.monitors[0]),'y')].set_value(0)
    report['main_canvas_display_drag']='passed'
    first=win.monitors[0]
    for key,value in (('width',3840),('height',2160)):
        field=win.monitor_fields[(id(first),key)]
        number_entry(field).set_text(str(value)); number_entry(field).emit('activate')
        assert getattr(first,key)==value
    second=win.monitors[1]
    for key,value in (('width',1920),('height',1080),('x',-1920),('y',120)):
        field=win.monitor_fields[(id(second),key)]
        number_entry(field).set_text(str(value)); number_entry(field).emit('activate')
        assert getattr(second,key)==value
    capture(win,'monitor-arrangement')
    panel_row(win,'Use this wallpaper size').emit('clicked')
    assert (win.width,win.height)==(5760,2160)
    report['monitor_exact_fields_and_apply']='passed'
    win.show_history(); later(history)


@guard
def history():
    win=app.get_active_window(); capture(win,'export-history')
    win.action_center.fold_panel()
    Gio.Settings.new('org.project_luma.shell-state').set_string('surface-treatment','dark')
    later(dark)


@guard
def dark():
    win=app.get_active_window(); assert Adw.StyleManager.get_default().get_dark()
    capture(win,'dark')
    Gio.Settings.new('org.project_luma.shell-state').set_string('surface-treatment','light')
    later(light)


@guard
def light():
    win=app.get_active_window(); assert not Adw.StyleManager.get_default().get_dark()
    capture(win,'light')
    settings=Gtk.Settings.get_default(); settings.set_property('gtk-enable-animations',False)
    settings.set_property('gtk-xft-dpi',int(96*1024*1.25))
    Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
    win.set_direction(Gtk.TextDirection.RTL)
    win.open_panel('adjust'); later(rtl)


@guard
def rtl():
    win=app.get_active_window(); capture(win,'rtl-large-text')
    assert win.action_center.bar.get_direction()==Gtk.TextDirection.RTL
    assert win.creation.get_page()=='adjust'
    ok,panel_bounds=win.creation.compute_bounds(win.host)
    preview_ok,preview_bounds=win.picture.compute_bounds(win.host)
    assert ok and preview_ok and preview_bounds.get_x()>=panel_bounds.get_x()+panel_bounds.get_width(),'Preview overlaps native left panel in RTL'
    # Native range keyboard controller: arrows change the value; Esc folds the bar.
    slider=win.controls['angle']; old=slider.value
    number_key(slider,Gdk.KEY_Up)
    assert slider.value!=old
    bar_keys=win.action_center.bar.observe_controllers()
    for i in range(bar_keys.get_n_items()):
        key=bar_keys.get_item(i)
        if isinstance(key,Gtk.EventControllerKey): key.emit('key-pressed',Gdk.KEY_Escape,0,Gdk.ModifierType(0))
    assert win.action_center.grown is None
    report['keyboard_range_escape']='passed'
    report['appearance_modes']=['dark','light','RTL / 125% text / animations disabled']
    win.bar_anchor('more').emit('clicked')
    later(more_menu_check)
    return False

@guard
def more_menu_check():
    win=app.get_active_window()
    from luma_appkit.action_bubble import FloatingMenu
    menus=[w for w in descendants(win) if isinstance(w,FloatingMenu) and w.get_visible()]
    assert menus,'Native More menu did not open'
    capture(win,'more-menu'); menus[0].close()
    report['native_more_menu']='passed'
    finish(); return False

app.connect('activate',lambda *_:later(start,1200))
app.run(None)
if errors: sys.exit(1)
