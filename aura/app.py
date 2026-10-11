"""Aura's native Luma AppKit application."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import threading
import time
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
gi.require_version('LumaUI','1')
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, LumaUI, Pango
from luma_appkit import AppWindow, Island, IslandSplitView, Toolbar, StatusBar, Command, CommandGroup, CommandRegistry, install_appkit, NumericField, ColorSwatch, IconButton, SectionLabel
from .model import Design, Monitor, PALETTES, EFFECTS, PRESETS, bounds, dimensions
from .render import pixels, export_png, Cancelled
from .store import Library

APP_ID='io.github.nmcmil.Aura'

def label(text): return Gtk.Label(label=text,xalign=0,wrap=True)
def box(spacing=12): return Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=spacing)
def padded(widget, margin=16):
    for side in ('top','bottom','start','end'): getattr(widget,'set_margin_'+side)(margin)
    return widget

def button(text, callback):
    b=Gtk.Button(label=text); b.connect('clicked',lambda *_: callback()); return b

def scroll(child):
    s=Gtk.ScrolledWindow(vexpand=True,hexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
    s.set_child(child); return s

class Window(AppWindow):
    def __init__(self,app):
        self.library=Library(); self.design=Design(); self.design_id=None
        self.undo_stack=[]; self.redo_stack=[]; self.loading=False
        self.preview_pool=ThreadPoolExecutor(max_workers=1)
        self.export_pool=ThreadPoolExecutor(max_workers=1)
        self.preview_busy=False; self.rendering_revision=-1; self.revision=0; self.preview_timer=0
        self.exporting=False; self.cancel_event=threading.Event()
        self.width,self.height=3840,2160
        self.monitors=[Monitor()]
        self.controls={}; self.number_fields={}; self.parameter_rows={}
        self.compact=False; self.gesture_active=False; self.gesture_checkpoint=False; self.last_edit=0
        self.commands=CommandRegistry([CommandGroup('Design',(
            Command('design.surprise','Surprise me',self.surprise,shortcut=('Ctrl','N')),
            Command('design.save','Save design',self.save,shortcut=('Ctrl','S')),
            Command('design.copy','Save as new design',self.save_copy,shortcut=('Ctrl','Shift','S')),
            Command('design.undo','Undo',self.undo,shortcut=('Ctrl','Z')),
            Command('design.redo','Redo',self.redo,shortcut=('Ctrl','Shift','Z')),
            Command('design.import','Import recipe',self.import_recipe),
            Command('design.share','Export recipe',self.share_recipe),
            Command('library.open','Saved designs',self.show_library,shortcut=('Ctrl','O')),
            Command('exports.open','Export history',self.show_history),
            Command('image.export','Export wallpaper',self.show_export,shortcut=('Ctrl','E')),
            Command('image.cancel','Cancel export',self.cancel_event.set,enabled=lambda:self.exporting),
            Command('design.reset','Reset adjustments',self.reset_adjustments),
            Command('canvas.monitors','Monitor layout',self.show_monitors),
        ))])
        super().__init__(application=app,app_id=APP_ID,title='Aura',icon_name=APP_ID,
                         commands=self.commands,default_width=1180,default_height=780,minimum_width=360,minimum_height=420)
        # Sibling AppKit islands use the body's authoritative 9px gutter.
        self.work=Island(); self.work.set_hexpand(True); self.work.set_vexpand(True)
        preview_bar=Toolbar()
        self.adjust_button=self.icon('preferences-system-symbolic','Adjust wallpaper',lambda:self.show_editor(True))
        self.adjust_button.set_visible(False); preview_bar.append(self.adjust_button)
        preview_bar.append(self.icon('folder-open-symbolic','Saved designs',self.show_library))
        self.title_label=label(self.design.name); self.title_label.set_wrap(False)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END); self.title_label.set_hexpand(True)
        preview_bar.append(self.title_label)
        preview_bar.append(self.icon('edit-undo-symbolic','Undo · Ctrl Z',self.undo))
        preview_bar.append(self.icon('edit-redo-symbolic','Redo · Ctrl Shift Z',self.redo))
        preview_bar.append(self.icon('document-save-symbolic','Save design · Ctrl S',self.save))
        export=button('Export',self.show_export); export.add_css_class('suggested-action'); preview_bar.append(export)
        self.work.append(preview_bar)
        self.picture=Gtk.Picture(can_shrink=True,hexpand=True,vexpand=True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.update_property([Gtk.AccessibleProperty.LABEL],['Wallpaper preview'])
        padded(self.picture,24); self.work.append(self.picture)
        self.work.append(self.make_canvas_controls())
        status=StatusBar(); self.status=status.append_text('Rendering preview…')
        self.status.set_ellipsize(Pango.EllipsizeMode.END); self.status.set_hexpand(True)
        self.cancel_button=button('Cancel export',self.cancel_event.set); self.cancel_button.set_visible(False)
        status.append(self.cancel_button); self.work.append(status)
        self.inspector=Island(); self.inspector.set_size_request(300,-1)
        self.inspector.set_vexpand(True)
        inspector_bar=Toolbar(); studio=label('Studio'); studio.set_hexpand(True); inspector_bar.append(studio)
        inspector_bar.append(self.icon('view-refresh-symbolic','Surprise me · Ctrl N',self.surprise))
        self.done_button=button('Done',lambda:self.show_editor(False)); self.done_button.set_visible(False)
        inspector_bar.append(self.done_button); self.inspector.append(inspector_bar)
        self.small_picture=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.CONTAIN,height_request=140)
        self.small_picture.set_visible(False); self.inspector.append(self.small_picture)
        self.inspector.append(self.make_inspector())
        self.body.append(self.inspector); self.body.append(self.work)
        breakpoint=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 700sp'))
        breakpoint.connect('apply',lambda *_:self.set_compact(True))
        breakpoint.connect('unapply',lambda *_:self.set_compact(False))
        self.add_breakpoint(breakpoint)
        self.connect('close-request',self.close_requested)
        try:
            draft=self.library.root/'draft.json'
            if draft.exists():
                saved=json.loads(draft.read_text())
                self.design=Design.from_dict(saved.get('design',saved))
                if 'canvas' in saved: self.width,self.height=dimensions(*saved['canvas'])
                if 'monitors' in saved:
                    self.monitors=[Monitor(**m) for m in saved['monitors']]; bounds(self.monitors)
                self.sync_controls()
        except (ValueError,TypeError,AttributeError,OSError): pass
        self.queue_preview()

    def icon(self,name,title,callback):
        b=IconButton(name,title,context=self.context,quiet=True)
        b.connect('clicked',lambda *_:callback()); return b
    def set_compact(self,compact):
        self.compact=compact; self.adjust_button.set_visible(compact); self.done_button.set_visible(compact)
        self.canvas_controls.set_orientation(Gtk.Orientation.VERTICAL if compact else Gtk.Orientation.HORIZONTAL)
        self.small_picture.set_visible(compact); self.inspector.set_hexpand(compact)
        self.inspector.set_size_request(-1 if compact else 300,-1)
        self.show_editor(False)
    def show_editor(self,show):
        self.inspector.set_visible(show or not self.compact)
        self.work.set_visible(not show or not self.compact)
    def make_canvas_controls(self):
        self.canvas_controls=Gtk.Box(spacing=12); padded(self.canvas_controls,12)
        self.canvas_names=('4K desktop','49″ ultrawide','Dual 4K','Phone','Tablet','16K square','Custom')
        self.canvas_presets=Gtk.DropDown.new_from_strings(self.canvas_names)
        self.canvas_presets.update_property([Gtk.AccessibleProperty.LABEL],['Canvas size preset'])
        self.canvas_presets.connect('notify::selected',self.canvas_preset_changed)
        self.canvas_controls.append(self.canvas_presets)
        dimensions_row=Gtk.Box(spacing=8,hexpand=True)
        self.canvas_width=NumericField('W',unit='px',minimum=1,maximum=32000)
        self.canvas_height=NumericField('H',unit='px',minimum=1,maximum=32000)
        for field,title in ((self.canvas_width,'Canvas width'),(self.canvas_height,'Canvas height')):
            field.set_hexpand(True); field.entry.set_width_chars(5)
            field.entry.update_property([Gtk.AccessibleProperty.LABEL],[title]); dimensions_row.append(field)
        self.canvas_width.set_value(self.width); self.canvas_height.set_value(self.height)
        self.canvas_width.connect('value-changed',lambda _,v:self.set_canvas(round(v),self.height))
        self.canvas_height.connect('value-changed',lambda _,v:self.set_canvas(self.width,round(v)))
        dimensions_row.append(self.icon('object-rotate-right-symbolic','Rotate canvas',lambda:self.set_canvas(self.height,self.width)))
        dimensions_row.append(self.icon('video-display-symbolic','Arrange multiple displays',self.show_monitors))
        self.canvas_controls.append(dimensions_row); return self.canvas_controls
    def canvas_preset_changed(self,widget,*_):
        if self.loading: return
        index=widget.get_selected()
        if index<len(PRESETS): self.set_canvas(*list(PRESETS.values())[index])
    def set_canvas(self,width,height):
        try: dimensions(width,height)
        except ValueError as e: self.error(str(e)); self.sync_canvas(); return
        self.width,self.height=width,height; self.sync_canvas(); self.queue_preview()
    def sync_canvas(self):
        previous=self.loading; self.loading=True
        sizes=list(PRESETS.values())
        self.canvas_presets.set_selected(sizes.index((self.width,self.height)) if (self.width,self.height) in sizes else len(sizes))
        self.canvas_width.set_value(self.width); self.canvas_height.set_value(self.height)
        self.loading=previous

    def reset_adjustments(self):
        self.checkpoint(); defaults=Design()
        for key in self.number_fields: setattr(self.design,key,getattr(defaults,key))
        self.sync_controls(); self.queue_preview()

    def close_requested(self,*_):
        if self.exporting:
            self.status.set_label('Cancel the export or wait for it to finish before closing.'); return True
        self.write_draft(); self.preview_pool.shutdown(wait=False,cancel_futures=True)
        self.export_pool.shutdown(wait=False,cancel_futures=True); return False

    def write_draft(self):
        try:
            p=self.library.root/'draft.json'; t=p.with_suffix('.tmp')
            from dataclasses import asdict
            t.write_text(json.dumps({'design':self.design.to_dict(),'canvas':[self.width,self.height],
                                     'monitors':[asdict(m) for m in self.monitors]})); t.replace(p)
        except OSError as e: self.status.set_label(f'Could not save draft: {e}')

    def make_inspector(self):
        panel=padded(box(14))
        self.name=Gtk.Entry(text=self.design.name,placeholder_text='Name your design')
        self.name.update_property([Gtk.AccessibleProperty.LABEL],['Design name'])
        self.name.connect('changed',lambda w:self.change('name',w.get_text()[:200])); panel.append(self.name)
        for key,title,options in [('effect','Effect',EFFECTS),('palette','Palette',tuple(PALETTES)+('Custom',))]:
            row=Gtk.Box(spacing=12); heading=label(title); heading.set_hexpand(True); row.append(heading)
            drop=Gtk.DropDown.new_from_strings(options)
            drop.update_property([Gtk.AccessibleProperty.LABEL],[title])
            drop.connect('notify::selected',lambda w,_,k=key,o=options:self.change(k,o[w.get_selected()]))
            self.controls[key]=drop; row.append(drop); panel.append(row)
        self.swatches=Gtk.Box(spacing=8); panel.append(self.swatches); self.refresh_swatches()
        panel.append(SectionLabel('Shape & light'))
        for key,title,lo,hi,step,unit,factor in [
          ('softness','Softness',0,1,.01,'%',100),('scale','Spread',.1,1.5,.01,'%',100),
          ('angle','Rotation',-180,180,1,'°',1),('center_x','Horizontal',0,1,.01,'%',100),
          ('center_y','Vertical',0,1,.01,'%',100),('edge','Outer edges',0,1,.01,'%',100),
          ('frequency','Repetition',2,48,1,'',1),('grain','Grain',0,1,.01,'%',100)]:
            group=box(2); row=Gtk.Box(spacing=6)
            number=NumericField(title,unit=unit,step=step*factor,minimum=lo*factor,maximum=hi*factor)
            number.set_hexpand(True); number.label.set_hexpand(True); number.label.set_xalign(0)
            number.entry.set_hexpand(False); number.entry.set_width_chars(4); number.entry.set_max_width_chars(4)
            number.set_value(getattr(self.design,key)*factor)
            number.entry.update_property([Gtk.AccessibleProperty.LABEL],[title+' value'])
            number.connect('value-changed',lambda w,v,k=key,f=factor:self.numeric_change(k,v/f))
            row.append(number)
            reset=self.icon('edit-undo-symbolic','Reset '+title.lower(),lambda k=key:self.numeric_change(k,getattr(Design(),k)))
            row.append(reset); group.append(row)
            slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,lo,hi,step)
            slider.set_value(getattr(self.design,key)); slider.set_draw_value(False)
            slider.update_property([Gtk.AccessibleProperty.LABEL],[title])
            # Native GTK stop values offer magnetic snapping without fighting the pointer.
            stops=(-180,-90,-45,0,45,90,180) if key=='angle' else (getattr(Design(),key),)
            if key in ('center_x','center_y'): stops=(.25,.5,.75,getattr(Design(),key))
            for stop in sorted(set(stops)): slider.add_mark(stop,Gtk.PositionType.BOTTOM,None)
            slider.connect('value-changed',lambda w,k=key:self.change(k,w.get_value()))
            gesture=Gtk.GestureClick(); gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            gesture.connect('pressed',lambda *_:self.begin_gesture()); gesture.connect('released',lambda *_:self.end_gesture())
            slider.add_controller(gesture)
            self.controls[key]=slider; self.number_fields[key]=(number,factor); self.parameter_rows[key]=group
            group.append(slider); panel.append(group)
        panel.append(button('Reset adjustments',self.reset_adjustments))
        panel.append(button('Export history',self.show_history))
        self.parameter_rows['frequency'].set_visible(self.design.effect in ('Stripes','Fluted','Waves'))
        return scroll(panel)

    def refresh_swatches(self):
        while self.swatches.get_first_child(): self.swatches.remove(self.swatches.get_first_child())
        for i,c in enumerate(self.design.colors):
            swatch=ColorSwatch(c,f'Edit color {i+1} · {c}',context=self.context)
            swatch.connect('clicked',lambda _,index=i:self.pick_color(index)); self.swatches.append(swatch)
        self.swatches.append(self.icon('preferences-other-symbolic','Edit palette',self.edit_colors))
    def pick_color(self,index):
        rgba=Gdk.RGBA(); rgba.parse(self.design.colors[index])
        dialog=Gtk.ColorDialog(title=f'Palette color {index+1}',with_alpha=False)
        def selected(d,res):
            try: color=d.choose_rgba_finish(res)
            except GLib.Error: return
            self.set_color(index,color)
        dialog.choose_rgba(self,rgba,None,selected)
    def set_color(self,index,rgba):
        color='#'+''.join(f'{round(v*255):02x}' for v in (rgba.red,rgba.green,rgba.blue))
        if color==self.design.colors[index]: return
        self.checkpoint(); self.design.colors=list(self.design.colors); self.design.colors[index]=color
        self.design.palette='Custom'; self.sync_controls(); self.queue_preview()
    def numeric_change(self,key,value):
        self.change(key,value); self.sync_controls()
    def begin_gesture(self): self.gesture_active=True; self.gesture_checkpoint=False
    def end_gesture(self): self.gesture_active=False; self.gesture_checkpoint=False

    def checkpoint(self):
        self.undo_stack.append(self.design.to_dict()); self.undo_stack=self.undo_stack[-100:]; self.redo_stack.clear()
    def change(self,key,value):
        if self.loading or getattr(self.design,key)==value: return
        if not self.gesture_active or not self.gesture_checkpoint:
            self.checkpoint(); self.gesture_checkpoint=True
        setattr(self.design,key,value)
        if key=='palette' and value in PALETTES: self.design.colors=list(PALETTES[value])
        if key in ('palette','colors'): self.refresh_swatches()
        if key in self.number_fields:
            field,factor=self.number_fields[key]; field.set_value(value*factor)
        if key=='effect': self.parameter_rows['frequency'].set_visible(value in ('Stripes','Fluted','Waves'))
        self.last_edit=time.monotonic()
        self.queue_preview()
    def sync_controls(self):
        self.loading=True; self.name.set_text(self.design.name)
        for key,w in self.controls.items():
            if key=='effect': w.set_selected(EFFECTS.index(self.design.effect))
            elif key=='palette': w.set_selected(list(PALETTES).index(self.design.palette) if self.design.palette in PALETTES else len(PALETTES))
            else: w.set_value(getattr(self.design,key))
        for key,(field,factor) in self.number_fields.items(): field.set_value(getattr(self.design,key)*factor)
        self.sync_canvas(); self.refresh_swatches(); self.parameter_rows['frequency'].set_visible(self.design.effect in ('Stripes','Fluted','Waves'))
        self.loading=False
    def set_design(self,d,identity=None):
        self.checkpoint(); self.design=d; self.design_id=identity; self.sync_controls(); self.queue_preview()
    def surprise(self): self.set_design(Design.surprise())
    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.design.to_dict()); self.design=Design.from_dict(self.undo_stack.pop()); self.sync_controls(); self.queue_preview()
    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.design.to_dict()); self.design=Design.from_dict(self.redo_stack.pop()); self.sync_controls(); self.queue_preview()
    def save(self):
        try:
            self.design_id=self.library.save(self.design,self.design_id); self.status.set_label('Design saved to your library')
        except Exception as e: self.error(str(e))
    def save_copy(self): self.design_id=None; self.save()
    def queue_preview(self):
        self.revision+=1; self.title_label.set_label(self.design.name or 'Untitled')
        if not self.preview_timer: self.preview_timer=GLib.timeout_add(16,self.start_preview)
    def start_preview(self):
        self.preview_timer=0
        if self.preview_busy or self.rendering_revision==self.revision: return False
        self.preview_busy=True; revision=self.revision; self.rendering_revision=revision
        d=Design.from_dict(self.design.to_dict())
        fit=min(860/self.width,540/self.height)
        w=max(1,round(self.width*fit)); h=max(1,round(self.height*fit))
        future=self.preview_pool.submit(pixels,d,w,h)
        def ready(f):
            try: result=f.result(); GLib.idle_add(self.finish_preview,revision,w,h,result,None)
            except Exception as e: GLib.idle_add(self.finish_preview,revision,w,h,None,str(e))
        future.add_done_callback(ready); return False
    def finish_preview(self,revision,w,h,result,error):
        self.preview_busy=False
        # Present every completed frame during a drag, then render the latest state.
        # Rejecting intermediate revisions would starve the live preview.
        if error: self.status.set_label(error)
        else:
            data=GLib.Bytes.new(result.tobytes())
            texture=Gdk.MemoryTexture.new(w,h,Gdk.MemoryFormat.R8G8B8,data,w*3)
            self.picture.set_paintable(texture); self.small_picture.set_paintable(texture)
            if not self.exporting: self.status.set_label(f'{self.width:,} × {self.height:,}  ·  {self.design.effect}')
            if revision==self.revision: self.write_draft()
        if revision!=self.revision:
            self.start_preview()
        return False

    def dialog(self,title,child,width=520,height=600):
        d=Adw.Dialog(title=title,content_width=width,content_height=height)
        view=Adw.ToolbarView(); view.add_top_bar(Adw.HeaderBar()); view.set_content(child); d.set_child(view); d.present(self); return d
    def error(self,message):
        d=Adw.AlertDialog(heading='Something needs attention',body=message)
        d.add_response('ok','OK'); d.present(self)
    def edit_colors(self):
        panel=padded(box()); panel.append(label('Make it yours. Edit the colors from the outside of the gradient to its center.'))
        wells=[]; updating=[False]
        for i,c in enumerate(self.design.colors):
            well=LumaUI.ColorWell.new(); rgba=Gdk.RGBA(); rgba.parse(c); well.set_rgba(rgba)
            well.update_property([Gtk.AccessibleProperty.LABEL],[f'Palette color {i+1}'])
            well.connect('changed',lambda w,index=i:None if updating[0] else self.set_color(index,w.get_rgba()))
            wells.append(well); panel.append(well)
        def reverse():
            self.reverse_palette(); updating[0]=True
            for well,color in zip(wells,self.design.colors):
                rgba=Gdk.RGBA(); rgba.parse(color); well.set_rgba(rgba)
            updating[0]=False
        panel.append(button('Reverse palette',reverse))
        self.dialog('Your palette',panel,height=380)
    def reverse_palette(self):
        self.checkpoint(); self.design.colors=list(reversed(self.design.colors)); self.design.palette='Custom'
        self.sync_controls(); self.queue_preview()

    def show_library(self):
        panel=padded(box()); panel.append(button('Save current as a new design',self.save_copy))
        rows=self.library.designs()
        if not rows: panel.append(label('Your collection starts here. Save a design, then return to it anytime.'))
        d=self.dialog('Your designs',scroll(panel),width=620)
        for identity,design,date in rows:
            row=box(6)
            thumb=Gtk.Picture(can_shrink=True); thumb.set_size_request(-1,110)
            arr=pixels(design,400,130); thumb.set_paintable(Gdk.MemoryTexture.new(400,130,Gdk.MemoryFormat.R8G8B8,GLib.Bytes.new(arr.tobytes()),1200)); row.append(thumb)
            row.append(button(f'{design.name} · {design.effect}',lambda x=design,i=identity:(self.set_design(x,i),d.close())))
            panel.append(row)
    def show_history(self):
        panel=padded(box()); rows=self.library.exports()
        if not rows: panel.append(label('Finished exports will appear here with the exact design used.'))
        d=self.dialog('Export history',scroll(panel),width=620)
        for path,w,h,design,date in rows:
            fit=min(480/w,140/h); tw=max(1,round(w*fit)); th=max(1,round(h*fit))
            thumb=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.CONTAIN)
            arr=pixels(design,tw,th)
            thumb.set_paintable(Gdk.MemoryTexture.new(tw,th,Gdk.MemoryFormat.R8G8B8,GLib.Bytes.new(arr.tobytes()),tw*3))
            panel.append(thumb)
            panel.append(label(f'{design.name}\n{w:,} × {h:,} · {date}\n{path}'))
            actions=Gtk.Box(spacing=8)
            actions.append(button('Use design',lambda x=design:(self.set_design(x),d.close())))
            actions.append(button('Open image',lambda p=path:self.open_file(p))); panel.append(actions)
    def open_file(self,path):
        if not Path(path).is_file(): self.error('This export has been moved or removed. Its design is still available.'); return
        Gtk.FileLauncher.new(Gio.File.new_for_path(path)).launch(self,None,None)
    def import_recipe(self):
        chooser=Gtk.FileDialog(title='Open Aura recipe')
        def done(c,res):
            try:
                p=c.open_finish(res).get_path()
                if Path(p).stat().st_size>64000: raise ValueError('Recipe is too large')
                self.set_design(Design.from_dict(json.loads(Path(p).read_text())))
            except GLib.Error: pass
            except Exception as e: self.error(str(e))
        chooser.open(self,None,done)
    def share_recipe(self):
        chooser=Gtk.FileDialog(title='Export editable recipe',initial_name='design.aura.json')
        recipe=self.design.to_dict()
        def done(c,res):
            try: Path(c.save_finish(res).get_path()).write_text(json.dumps(recipe,indent=2))
            except GLib.Error: pass
            except Exception as e: self.error(str(e))
        chooser.save(self,None,done)

    def spin(self,panel,title,value,low=1,high=32000):
        panel.append(label(title)); s=Gtk.SpinButton.new_with_range(low,high,1); s.set_value(value)
        s.update_property([Gtk.AccessibleProperty.LABEL],[title]); panel.append(s); return s
    def show_export(self):
        if self.exporting: self.error('An export is already running. You can keep designing while it finishes.'); return
        panel=padded(box()); panel.append(label(f'{self.width:,} × {self.height:,} pixels'))
        depth=Gtk.CheckButton(label='16-bit color · smoothest gradients',active=True); panel.append(depth)
        panel.append(label('Lossless PNG, rendered at the exact output size. Large exports run in the background.'))
        panel.append(button('Build a multi-monitor layout…',self.show_monitors))
        panel.append(button('Export a set of sizes…',lambda:self.show_batch(depth.get_active())))
        d=self.dialog('Export wallpaper',scroll(panel),height=390)
        def save():
            width,height=self.width,self.height
            try: dimensions(width,height)
            except ValueError as e: self.error(str(e)); return
            chooser=Gtk.FileDialog(title='Save wallpaper',initial_name=f'Aura-{width}x{height}.png')
            snapshot=Design.from_dict(self.design.to_dict())
            def selected(c,res):
                try: path=c.save_finish(res).get_path()
                except GLib.Error: return
                d.close(); self.run_exports([(path,width,height,None)],16 if depth.get_active() else 8,snapshot)
            chooser.save(self,None,selected)
        panel.append(button('Choose location & export',save))

    def show_batch(self,sixteen=True):
        panel=padded(box()); checks=[]
        for name,(w,h) in PRESETS.items():
            c=Gtk.CheckButton(label=f'{name} · {w:,} × {h:,}'); checks.append((c,w,h)); panel.append(c)
        panel.append(label('A new uniquely named folder keeps existing exports safe.'))
        d=self.dialog('Export a set',panel,height=440)
        def start():
            sizes=[(w,h) for c,w,h in checks if c.get_active()]
            if not sizes: return
            self.choose_folder(lambda folder:self.export_set(folder,sizes,16 if sixteen else 8)); d.close()
        panel.append(button('Choose folder & export set',start))
    def choose_folder(self,callback):
        chooser=Gtk.FileDialog(title='Choose export folder')
        def selected(c,res):
            try: callback(Path(c.select_folder_finish(res).get_path()))
            except GLib.Error: pass
            except Exception as e: self.error(str(e))
        chooser.select_folder(self,None,selected)
    def new_export_folder(self,parent):
        import datetime,uuid
        folder=parent/('Aura-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]); folder.mkdir(); return folder
    def export_set(self,parent,sizes,depth):
        folder=self.new_export_folder(parent)
        self.run_exports([(str(folder/f'{w}x{h}.png'),w,h,None) for w,h in sizes],depth)

    def show_monitors(self):
        panel=padded(box()); panel.append(label('Drag your displays into place, or enter exact pixel positions.'))
        canvas=Gtk.DrawingArea(content_height=200); panel.append(canvas)
        canvas.update_property([Gtk.AccessibleProperty.LABEL],['Monitor arrangement preview. Exact positions can be edited below.'])
        rows=box(16); panel.append(rows); drawing={}; fields={}; dragging={}
        summary=label(''); panel.append(summary)
        def describe():
            try:
                _,_,bw,bh=bounds(self.monitors)
                summary.set_label(f'Complete canvas · {bw:,} × {bh:,} pixels')
            except ValueError as e: summary.set_label(str(e))
        def draw(area,cr,w,h):
            try: x,y,bw,bh=bounds(self.monitors)
            except ValueError: return
            import cairo
            import numpy as np
            scale=min((w-32)/bw,(h-32)/bh)
            pw,ph=max(1,round(bw*scale)),max(1,round(bh*scale))
            rgb=pixels(self.design,pw,ph)
            bgra=np.empty((ph,pw,4),dtype=np.uint8); bgra[:,:,:3]=rgb[:,:,::-1]; bgra[:,:,3]=255
            surface=cairo.ImageSurface.create_for_data(bgra,cairo.FORMAT_ARGB32,pw,ph)
            left=(w-pw)/2; top=(h-ph)/2
            drawing.update(x=x,y=y,scale=scale,left=left,top=top)
            for i,m in enumerate(self.monitors):
                xx=left+(m.x-x)*scale; yy=top+(m.y-y)*scale
                cr.save(); cr.rectangle(xx,yy,m.width*scale,m.height*scale); cr.clip()
                cr.set_source_surface(surface,left,top); cr.paint(); cr.restore()
                cr.set_source_rgba(1,1,1,.8); cr.set_line_width(2)
                cr.rectangle(xx+1,yy+1,m.width*scale-2,m.height*scale-2); cr.stroke()
                cr.move_to(xx+8,yy+20); cr.show_text(str(i+1))
        canvas.set_draw_func(draw)
        def update(m,key,value):
            setattr(m,key,round(value)); describe(); canvas.queue_draw(); self.write_draft()
        def rebuild():
            fields.clear()
            while rows.get_first_child(): rows.remove(rows.get_first_child())
            for i,m in enumerate(self.monitors):
                group=box(8); header=Gtk.Box(spacing=8)
                heading=label(f'Display {i+1}'); heading.set_hexpand(True); header.append(heading)
                def rotate(m=m): m.width,m.height=m.height,m.width; rebuild(); canvas.queue_draw(); self.write_draft()
                header.append(self.icon('object-rotate-right-symbolic','Rotate display',rotate))
                if len(self.monitors)>1:
                    header.append(self.icon('list-remove-symbolic','Remove display',lambda monitor=m:(self.monitors.remove(monitor),rebuild(),canvas.queue_draw(),self.write_draft())))
                group.append(header)
                for pair in ((('width','W',1),('height','H',1)),(('x','X',-32000),('y','Y',-32000))):
                    line=Gtk.Box(spacing=12)
                    for key,title,lo in pair:
                        number=NumericField(title,unit='px',minimum=lo,maximum=32000)
                        number.set_hexpand(True); number.entry.set_width_chars(5)
                        number.entry.update_property([Gtk.AccessibleProperty.LABEL],[f'Display {i+1} {key}'])
                        number.set_value(getattr(m,key)); fields[(id(m),key)]=number
                        number.connect('value-changed',lambda _,v,k=key,monitor=m:update(monitor,k,v)); line.append(number)
                    group.append(line)
                rows.append(group)
            describe(); canvas.queue_draw()
        drag=Gtk.GestureDrag()
        def begin(_,px,py):
            dragging.clear()
            if not drawing: return
            x=(px-drawing['left'])/drawing['scale']+drawing['x']; y=(py-drawing['top'])/drawing['scale']+drawing['y']
            for m in reversed(self.monitors):
                if m.x<=x<=m.x+m.width and m.y<=y<=m.y+m.height:
                    dragging.update(monitor=m,x=m.x,y=m.y,scale=drawing['scale']); break
        def move(_,dx,dy):
            if not dragging: return
            m=dragging['monitor']; x=round(dragging['x']+dx/dragging['scale']); y=round(dragging['y']+dy/dragging['scale'])
            tolerance=8/dragging['scale']
            for other in self.monitors:
                if other is m: continue
                for snap in (other.x,other.x+other.width,other.x-m.width):
                    if abs(x-snap)<tolerance: x=snap; break
                for snap in (other.y,other.y+other.height,other.y-m.height):
                    if abs(y-snap)<tolerance: y=snap; break
            m.x=max(-32000,min(32000,x)); m.y=max(-32000,min(32000,y))
            fields[(id(m),'x')].set_value(m.x); fields[(id(m),'y')].set_value(m.y); describe(); canvas.queue_draw()
        drag.connect('drag-begin',begin); drag.connect('drag-update',move)
        drag.connect('drag-end',lambda *_:self.write_draft()); canvas.add_controller(drag)
        rebuild()
        def add():
            if len(self.monitors)<8:
                x=max(m.x+m.width for m in self.monitors); self.monitors.append(Monitor(x=x)); rebuild(); self.write_draft()
        panel.append(button('Add display',add))
        panel.append(label('Pixel-based alignment. Adjust gaps manually for bezels or mixed display sizes.'))
        d=self.dialog('Your monitor layout',scroll(panel),width=560,height=700)
        def layout_snapshot():
            layout=[replace(m) for m in self.monitors]; return layout,bounds(layout)
        def apply():
            try: layout,(_,_,w,h)=layout_snapshot()
            except ValueError as e: self.error(str(e)); return
            self.set_canvas(w,h); self.write_draft(); d.close()
        panel.append(button('Use this canvas',apply))
        def start():
            try: layout,(x,y,w,h)=layout_snapshot()
            except ValueError as e: self.error(str(e)); return
            self.set_canvas(w,h)
            def export(parent):
                folder=self.new_export_folder(parent)
                jobs=[(str(folder/'complete-span.png'),w,h,None)]
                jobs += [(str(folder/f'display-{i+1}.png'),m.width,m.height,(m.x-x,m.y-y,w,h)) for i,m in enumerate(layout)]
                self.run_exports(jobs,16); d.close()
            self.choose_folder(export)
        panel.append(button('Export span & display images…',start))

    def run_exports(self,jobs,depth,design=None):
        if self.exporting: self.error('Wait for the current export to finish.'); return
        self.exporting=True; self.cancel_button.set_visible(True); self.cancel_event.clear(); snapshot=design or Design.from_dict(self.design.to_dict())
        panel=padded(box()); panel.append(label('Rendering your wallpaper'))
        bar=Gtk.ProgressBar(show_text=True); panel.append(bar)
        note=label('You can close this panel and keep designing.'); panel.append(note)
        panel.append(button('Cancel export',self.cancel_event.set))
        dialog=self.dialog('Exporting',panel,height=220)
        def progress(value,index):
            def update():
                fraction=(index+value)/len(jobs); bar.set_fraction(fraction); bar.set_text(f'{fraction:.0%}')
                self.status.set_label(f'Exporting · {fraction:.0%}'); return False
            GLib.idle_add(update)
        def work():
            complete=0
            try:
                for i,(path,w,h,region) in enumerate(jobs):
                    export_png(snapshot,path,w,h,depth=depth,region=region,progress=lambda v,index=i:progress(v,index),cancel=self.cancel_event)
                    self.library.record_export(path,w,h,snapshot); complete+=1
                message=f'Exported {complete} image'+('s' if complete!=1 else '')
            except Cancelled: message=f'Cancelled · {complete} completed images kept'
            except Exception as e: message=f'Export failed: {e}'
            GLib.idle_add(finish,message)
        def finish(message):
            self.exporting=False; self.cancel_button.set_visible(False); self.status.set_label(message); note.set_label(message)
            dialog.close(); self.dialog('Export result',padded(label(message)),height=180); return False
        self.export_pool.submit(work)

class Application(Adw.Application):
    def __init__(self):
        GLib.set_application_name('Aura'); GLib.set_prgname('aura')
        super().__init__(application_id=APP_ID,flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
    def do_activate(self):
        install_appkit()
        win=self.get_active_window()
        if not win: win=Window(self)
        win.present()

def main(): return Application().run(None)
