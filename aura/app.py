"""Aura's native Luma AppKit application."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import threading
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
gi.require_version('LumaUI','1')
from gi.repository import Gtk, Adw, Gdk, Gio, GLib, LumaUI, Pango, Graphene
from luma_appkit import (AppWindow, Island, Command, CommandGroup, CommandRegistry, install_appkit,
                         ColorSwatch, IconButton, ActionCenter, BarAction,
                         PanelRow, PanelHeading, PanelField,
                         ToastHost, Toast, MediaTile, TextField, FloatingPanel, CreativeWorkspace, TextButton, PropertySection, PropertyNumber, PropertyChoice, ValueSlider, evaluate_number, apply_type)
from .model import Design, Monitor, PALETTES, EFFECTS, PRESETS, bounds, dimensions
from .render import pixels, export_png, Cancelled
from .store import Library
from .studio import STYLE_NOTES, ADJUSTMENTS, adjustment_visible
from luma_appkit.lumaui_tokens import CREATIVE
from luma_appkit.action_bubble import MenuItem

APP_ID='io.github.nmcmil.Aura'

def label(text):
    result=Gtk.Label(label=text,xalign=0,wrap=True); apply_type(result,'body'); return result
def box(spacing=12): return Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=spacing)
def padded(widget, margin=16):
    for side in ('top','bottom','start','end'): getattr(widget,'set_margin_'+side)(margin)
    return widget

class PreviewViewport(Gtk.Widget):
    """Write's content viewport pattern: allocate app pixels at available size."""
    def __init__(self,child,on_allocate):
        super().__init__(hexpand=True,vexpand=True)
        self.child=child; child.set_parent(self); self.on_allocate=on_allocate

    def do_measure(self,orientation,for_size): return 1,1,-1,-1

    def do_size_allocate(self,width,height,baseline):
        self.on_allocate(width,height)
        allocation=Gdk.Rectangle(); allocation.x=0; allocation.y=0
        allocation.width=width; allocation.height=height
        self.child.size_allocate(allocation,baseline)

    def do_snapshot(self,snapshot):
        # App content shares the frame's named background, without an inset surface.
        found,color=self.get_style_context().lookup_color('luma_window')
        if found:
            bounds=Graphene.Rect(); bounds.init(0,0,self.get_width(),self.get_height())
            snapshot.append_color(color,bounds)
        self.snapshot_child(self.child,snapshot)

    def do_dispose(self):
        if self.child.get_parent() is self: self.child.unparent()

class ZoomPreview(Gtk.Widget):
    """Transform wallpaper pixels only; layout and export resolution stay fixed."""
    def __init__(self,child):
        super().__init__(hexpand=True,vexpand=True,overflow=Gtk.Overflow.HIDDEN)
        self.child=child; child.set_parent(self); self.zoom=1.0
        self.insets=(24,12,24,92); self.fit_rect=(0,0,1,1)

    def do_measure(self,orientation,for_size): return 1,1,-1,-1

    def do_size_allocate(self,width,height,baseline):
        left,top,right,bottom=self.insets
        w,h=max(1,width-left-right),max(1,height-top-bottom)
        self.fit_rect=(left,top,w,h)
        allocation=Gdk.Rectangle(); allocation.x=left; allocation.y=top
        allocation.width=w; allocation.height=h
        self.child.size_allocate(allocation,baseline)

    def do_snapshot(self,snapshot):
        snapshot.save()
        x,y,w,h=self.fit_rect
        point=Graphene.Point(); point.init(x+w/2,y+h/2)
        snapshot.translate(point); snapshot.scale(self.zoom,self.zoom)
        point.init(-x-w/2,-y-h/2); snapshot.translate(point)
        self.snapshot_child(self.child,snapshot); snapshot.restore()

    def do_dispose(self):
        if self.child.get_parent() is self: self.child.unparent()

class Window(AppWindow):
    def __init__(self,app):
        self.library=Library(); self.design=Design(); self.design_id=None
        self.undo_stack=[]; self.redo_stack=[]; self.loading=False; self.closed=False
        self.preview_pool=ThreadPoolExecutor(max_workers=1)
        self.export_pool=ThreadPoolExecutor(max_workers=1)
        self.thumbnail_pool=ThreadPoolExecutor(max_workers=1)
        self.thumbnail_jobs=[]; self.thumbnail_busy=False; self.thumbnail_epoch=0
        self.preview_busy=False; self.rendering_revision=-1; self.revision=0; self.preview_timer=0
        self.exporting=False; self.cancel_event=threading.Event()
        self.width,self.height=3840,2160; self.monitors=[Monitor()]
        self.controls={}; self.number_fields={}; self.parameter_rows={}; self.choice_buttons={}
        self.compact=False; self.gesture_active=False; self.gesture_checkpoint=False
        self.adjust_page='shape'; self.panel_key=None; self.creation_key=None; self.short=False
        self.commands=CommandRegistry([
            CommandGroup('Design',(
                Command('design.surprise','Surprise me',self.surprise,shortcut=('Ctrl','N')),
                Command('design.save','Save design',self.save,shortcut=('Ctrl','S')),
                Command('design.copy','Save a copy',self.save_copy,shortcut=('Ctrl','Shift','S')),
                Command('design.rename','Rename design',self.rename,shortcut=('F2',)),
                Command('design.undo','Undo',self.undo,shortcut=('Ctrl','Z'),enabled=lambda:bool(self.undo_stack)),
                Command('design.redo','Redo',self.redo,shortcut=('Ctrl','Shift','Z'),enabled=lambda:bool(self.redo_stack)),
                Command('design.import','Open recipe…',self.import_recipe),
                Command('design.share','Save recipe…',self.share_recipe),
                Command('library.open','Saved designs',self.show_library,shortcut=('Ctrl','O')),
            )),
            CommandGroup('Wallpaper',(
                Command('studio.style','Choose a style',lambda:self.open_panel('style')),
                Command('studio.colors','Choose colors',lambda:self.open_panel('colors')),
                Command('studio.adjust','Adjust wallpaper',lambda:self.show_editor(True)),
                Command('studio.size','Wallpaper size',lambda:self.open_panel('size')),
                Command('image.export','Export wallpaper…',self.show_export,shortcut=('Ctrl','E')),
                Command('image.cancel','Cancel export',self.cancel_event.set,enabled=lambda:self.exporting),
                Command('exports.open','Export history',self.show_history),
                Command('design.reset','Reset adjustments',self.reset_adjustments),
                Command('canvas.monitors','Arrange displays…',self.show_monitors),
                Command('view.zoom-in','Zoom in',lambda:self.zoom_by(1),shortcut=('Ctrl','plus')),
                Command('view.zoom-out','Zoom out',lambda:self.zoom_by(-1),shortcut=('Ctrl','minus')),
                Command('view.zoom-reset','Reset zoom',lambda:self.set_zoom(1),shortcut=('Ctrl','0')),
                Command('view.zoom-equal','Zoom in',lambda:self.zoom_by(1),shortcut=('Ctrl','equal')),
            )),
        ])
        super().__init__(application=app,app_id=APP_ID,title='Aura',icon_name=APP_ID,
                         commands=self.commands,default_width=1180,default_height=780,
                         minimum_width=360,minimum_height=420)
        self.work=box(0); self.work.set_hexpand(True); self.work.set_vexpand(True)
        self.picture=Gtk.Picture(can_shrink=True,hexpand=True,vexpand=True,
                                 content_fit=Gtk.ContentFit.CONTAIN)
        self.picture.update_property([Gtk.AccessibleProperty.LABEL],['Live wallpaper preview'])
        self.zoom_preview=ZoomPreview(self.picture)
        self.canvas_stack=Gtk.Stack(hexpand=True,vexpand=True,transition_type=Gtk.StackTransitionType.NONE)
        self.canvas_stack.set_hhomogeneous(False); self.canvas_stack.set_vhomogeneous(False)
        self.canvas_stack.add_named(self.zoom_preview,'wallpaper')

        self.zoom_scroll=Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        self.zoom_scroll.connect('scroll',self.scroll_zoom)
        self.zoom_preview.add_controller(self.zoom_scroll)
        self.picture.set_tooltip_text('Drag the wallpaper to move its color pattern')
        self.position_drag=Gtk.GestureDrag()
        self.position_drag.connect('drag-begin',self.position_begin)
        self.position_drag.connect('drag-update',self.position_move)
        self.position_drag.connect('drag-end',lambda *_:self.end_gesture())
        self.zoom_preview.add_controller(self.position_drag)
        self.work.append(self.canvas_stack)
        self.preview_host=Gtk.Overlay(child=self.work,hexpand=True,vexpand=True)
        self.creation_pages={key:box(0) for key in ('style','colors','adjust')}
        self.changing_creation=False
        self.creation=FloatingPanel('Create wallpaper','palette',
            pages=[(key,title,self.creation_pages[key]) for key,title in
                   (('style','Style'),('colors','Colors'),('adjust','Adjust'))],
            closable=False,on_page=self.creation_page_changed,
            on_folded=lambda *_:self.update_preview_space())
        self.creation.set_holds('inspector')
        self.space_pending=False
        self.preview_viewport=PreviewViewport(self.preview_host,self.preview_allocated)
        self.workspace=CreativeWorkspace(self.preview_viewport,left=self.creation,grid=False)
        self.workspace.set_hexpand(True); self.workspace.set_vexpand(True)
        self.host=ToastHost(self.workspace); self.host.set_hexpand(True); self.host.set_vexpand(True)
        self.surface=Island(); self.surface.set_hexpand(True); self.surface.set_vexpand(True)
        self.surface.append(self.host); self.body.append(self.surface)
        self.status=label(''); self.status.set_visible(False)
        self.action_center=ActionCenter().attach(self.host,over='frame',inset='tight')
        self.action_center.bar.update_property([Gtk.AccessibleProperty.LABEL],['Wallpaper studio'])
        # The panel is a short, scrollable editing surface. Leave a live preview above it.
        self.action_center.panel.set_max_content_height(260)
        self.action_center.connect('panel-changed',self.panel_changed)
        self.action_center.show_bar([
            BarAction('monitor','3,840 × 2,160',tooltip='Adjust wallpaper size',keep_label=True,
                      panel=lambda:self.make_panel('size'),key='size'),
            BarAction('ellipsis',tooltip='More actions',menu=self.more_menu,key='more'),
            BarAction('download','Export',tooltip='Export wallpaper',primary=True,on_activate=self.show_export),
        ])
        breakpoint=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 559sp'))
        breakpoint.connect('apply',lambda *_:self.set_compact(True))
        breakpoint.connect('unapply',lambda *_:self.set_compact(False))
        self.add_breakpoint(breakpoint)
        short=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-height: 550sp and min-width: 560sp'))
        short.connect('apply',lambda *_:self.set_short(True))
        short.connect('unapply',lambda *_:self.set_short(False))
        self.add_breakpoint(short)
        compact_short=Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 559sp and max-height: 550sp'))
        compact_short.connect('apply',lambda *_:(self.set_compact(True),self.set_short(True)))
        compact_short.connect('unapply',lambda *_:(self.set_compact(False),self.set_short(False)))
        self.add_breakpoint(compact_short)
        self.connect('close-request',self.close_requested)
        try:
            draft=self.library.root/'draft.json'
            if draft.exists():
                saved=json.loads(draft.read_text())
                self.design=Design.from_dict(saved.get('design',saved))
                if 'canvas' in saved: self.width,self.height=dimensions(*saved['canvas'])
                if 'monitors' in saved:
                    self.monitors=[Monitor(**m) for m in saved['monitors']]; bounds(self.monitors)
        except (ValueError,TypeError,AttributeError,OSError): pass
        self.show_creation('style')
        self.queue_preview()

    def icon(self,name,title,callback):
        b=IconButton(name,title,context=self.context,quiet=True)
        b.connect('clicked',lambda *_:callback()); return b

    def set_compact(self,compact):
        self.compact=compact
        self.update_preview_space()

    def set_short(self,short):
        self.short=short; self.update_preview_space()

    def panel_changed(self,center,key):
        self.panel_key=key or None
        arranging=key=='monitors'
        self.creation.set_visible(not arranging)
        self.canvas_stack.set_visible_child_name('monitors' if arranging else 'wallpaper')
        self.action_center.panel.set_max_content_height(120 if self.short else 220 if self.compact else 280 if arranging else 260)
        if self.compact and key: self.creation.set_folded(True)
        self.update_preview_space()

    def preview_allocated(self,width,height):
        self.update_preview_space(height)
        # Coalesce a geometry refresh after native workspace/overlay allocation.
        # Like ActionCenter's safe-area refresh, this runs only on allocation.
        if not self.space_pending:
            self.space_pending=True; GLib.idle_add(self.refresh_preview_space)

    def refresh_preview_space(self):
        self.space_pending=False
        if not self.closed: self.update_preview_space()
        return False

    def update_preview_space(self,height=None):
        # Reserve app-content space using the same CR1 metrics as Canvas/Write.
        # The native workspace owns all chrome allocation and bar clearance.
        if not hasattr(self,'workspace'): return
        opened=self.compact and self.panel_key!='monitors' and not self.creation.get_folded()
        width=0 if self.panel_key=='monitors' else CREATIVE['panel_left_width']+2*CREATIVE['panel_inset']
        left=0 if self.compact else width
        cap=0
        if opened:
            _,natural,*_=self.creation.measure(Gtk.Orientation.VERTICAL,max(1,self.workspace.get_width()))
            cap=min(natural,(height if height is not None else self.workspace.get_height())*CREATIVE['panel_phone_max_height_pct']//100)
        output_space=CREATIVE['panel_reserve']
        # Arrangement is a separate canvas mode: keep the screens above their controls.
        # Size/export overlays never change the wallpaper's fit rectangle.
        if self.panel_key=='monitors':
            ok,bounds=self.action_center.panel.compute_bounds(self.preview_viewport)
            if ok and bounds.get_height()>0:
                output_space=max(output_space,round((height if height is not None else self.preview_viewport.get_height())-bounds.get_y())+CREATIVE['panel_inset'])
        top=12 if opened or not self.compact or self.panel_key=='monitors' else 64
        available=height if height is not None else self.preview_viewport.get_height()
        # Keep a 64px live image while native overlay geometry settles on resize.
        bottom=min(max(cap,output_space),max(0,available-top-64)) if available else max(cap,output_space)
        arranging=self.panel_key=='monitors'
        self.canvas_stack.set_margin_start(24 if arranging else 0)
        self.canvas_stack.set_margin_end(24 if arranging else 0)
        self.canvas_stack.set_margin_top(top if arranging else 0)
        self.canvas_stack.set_margin_bottom(bottom if arranging else 0)
        insets=(left+24,top,24,bottom)
        if not arranging and self.zoom_preview.insets!=insets:
            self.zoom_preview.insets=insets; self.zoom_preview.queue_allocate()
        if hasattr(self,'action_center'): self.action_center.set_visible(not opened)

    def show_editor(self,show):
        if show: self.open_panel('adjust')
        else: self.action_center.fold_panel()

    def open_panel(self,key):
        if key in ('style','colors','adjust'):
            self.action_center.fold_panel(); self.show_creation(key); return
        self.action_center.grow(key,lambda:self.make_panel(key),anchor=self.bar_anchor(key))

    def creation_page_changed(self,key):
        if not self.changing_creation: self.show_creation(key)

    def show_creation(self,key):
        self.set_creation_content(key,self.make_panel(key))

    def set_creation_content(self,key,content):
        self.creation_key=key
        page='colors' if key=='edit-colors' else key
        holder=self.creation_pages[page]
        while holder.get_first_child(): holder.remove(holder.get_first_child())
        holder.append(content)
        self.changing_creation=True
        self.creation.set_page(page); self.creation.set_folded(False)
        self.changing_creation=False
        self.update_preview_space()

    def bar_anchor(self,key):
        child=self.action_center.bar_row.get_first_child()
        while child:
            item=getattr(child,'bar_item',None)
            if getattr(item,'key',None)==key: return child
            child=child.get_next_sibling()
        return None

    def make_panel(self,key):
        if key in ('style','colors','adjust'):
            self.thumbnail_epoch+=1; self.thumbnail_jobs=[]
            self.controls={}; self.number_fields={}; self.parameter_rows={}; self.choice_buttons={}
        if key=='style': return self.style_panel()
        if key=='colors': return self.colors_panel()
        if key=='adjust': return self.adjust_panel()
        if key=='size': return self.make_canvas_controls()
        raise ValueError(f'Unknown studio panel: {key}')

    def panel_header(self,title,description=None):
        panel=box(10); panel.append(PanelHeading(title))
        if description:
            note=label(description); apply_type(note,'caption'); panel.append(note)
        return panel

    def style_panel(self):
        panel=self.panel_header('Choose a style','Same colors. A different way to see them.')
        grid=Gtk.Grid(column_spacing=8,row_spacing=8,column_homogeneous=True)
        jobs=[]
        for i,effect in enumerate(EFFECTS):
            tile=MediaTile(kind='clip',title=effect,caption=effect,
                selected=self.design.effect==effect,on_activate=lambda name=effect:self.choose_style(name))
            tile.set_hexpand(True); tile.set_tooltip_text(STYLE_NOTES[effect])
            grid.attach(tile,i%2,i//2,1,1); self.choice_buttons[effect]=tile
            jobs.append((tile,replace(self.design,effect=effect),160,90))
        panel.append(grid)
        self.sync_choices(self.design.effect); self.load_thumbnails(jobs)
        return panel

    def choose_style(self,effect):
        self.change('effect',effect); self.sync_choices(effect)

    def sync_choices(self,selected):
        for key,tile in self.choice_buttons.items():
            if isinstance(tile,MediaTile): tile.set_selected(key==selected)

    def colors_panel(self):
        panel=box(0)
        grid=Gtk.Grid(column_spacing=8,row_spacing=8,column_homogeneous=True)
        self.palette_tiles={}
        choices=dict(PALETTES)
        if self.design.palette=='Custom': choices['Custom']=self.design.colors
        for i,(name,colors) in enumerate(choices.items()):
            tile=MediaTile(kind='clip',title=name,caption=name,selected=self.design.palette==name,
                           on_activate=lambda name=name:self.choose_palette(name))
            tile.set_hexpand(True)
            tile.set_picture(self.palette_strip(colors,160,90).get_paintable())
            grid.attach(tile,i%2,i//2,1,1); self.palette_tiles[name]=tile
        panel.append(PropertySection('Palette',grid))
        actions=box(6)
        actions.append(TextButton('Edit colors',icon='palette',style='fill',small=True,on_click=self.edit_colors))
        actions.append(TextButton('Reverse colors',icon='arrow-left-right',style='fill',small=True,on_click=self.reverse_palette))
        panel.append(PropertySection('Colors',actions))
        return panel

    def palette_strip(self,colors,width=96,height=24):
        import numpy as np
        rgb=np.array([[int(c[i:i+2],16) for i in (1,3,5)] for c in colors],dtype=np.uint8)
        arr=np.repeat(rgb[(np.arange(width)*len(colors)//width)][None,:,:],height,axis=0)
        w=arr.shape[1]
        thumb=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.FILL,width_request=width,height_request=height)
        thumb.set_paintable(Gdk.MemoryTexture.new(w,height,Gdk.MemoryFormat.R8G8B8,GLib.Bytes.new(arr.tobytes()),w*3))
        return thumb

    def choose_palette(self,name):
        self.change('palette',name)
        self.set_creation_content('colors',self.colors_panel())

    def adjust_panel(self):
        panel=box(0); self.adjust_stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.adjust_stack.set_vhomogeneous(False)
        tabs=PropertyChoice('Adjustment',[(key,title) for key,title in (('shape','Shape'),('position','Position'),('finish','Finish'))],
            current=self.adjust_page,segments=True,on_change=self.select_adjust_page)
        self.adjust_tabs=tabs
        panel.append(PropertySection('Adjust',tabs))
        pages={key:PropertySection(title) for key,title in (('shape','Shape'),('position','Position'),('finish','Finish'))}
        for key,title,lo,hi,step,unit,factor,page in ADJUSTMENTS:
            if key=='edge' and self.design.effect not in ('Glow','Halo'): title='Edge shading'
            field=ValueSlider(title,getattr(self.design,key)*factor,lo*factor,hi*factor,unit=unit or '',
                default=getattr(Design(),key)*factor,step=step*factor,layout='editor',
                on_change=lambda value,k=key,f=factor:self.change(k,value/f))
            gesture=Gtk.GestureClick(); gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            gesture.connect('pressed',lambda *_:self.begin_gesture())
            gesture.connect('released',lambda *_:self.end_gesture()); field.add_controller(gesture)
            child=field.get_first_child()
            while child:
                controllers=child.observe_controllers()
                for i in range(controllers.get_n_items()):
                    controller=controllers.get_item(i)
                    if isinstance(controller,Gtk.GestureDrag):
                        controller.connect('drag-begin',lambda *_:self.begin_gesture())
                        controller.connect('drag-end',lambda *_:self.end_gesture())
                child=child.get_next_sibling()
            self.controls[key]=field; self.number_fields[key]=(field,factor); self.parameter_rows[key]=field
            field.set_visible(adjustment_visible(key,self.design.effect)); pages[page].append(field)
        for key,page in pages.items(): self.adjust_stack.add_named(page,key)
        self.adjust_stack.set_visible_child_name(self.adjust_page); panel.append(self.adjust_stack)
        panel.append(PropertySection('Defaults',TextButton('Reset adjustments',icon='rotate-ccw',style='fill',small=True,on_click=self.reset_adjustments)))
        return panel

    def select_adjust_page(self,key):
        self.adjust_page=key; self.adjust_stack.set_visible_child_name(key)
        if self.adjust_tabs.get_current()!=key: self.adjust_tabs.set_current(key)

    def make_canvas_controls(self):
        panel=box(0)
        selected=next((name for name,size in PRESETS.items() if size==(self.width,self.height)),'custom')
        picker=PropertyChoice('Screen preset',[(name,f'{name} · {w:,} × {h:,}') for name,(w,h) in PRESETS.items()]+[('custom','Custom size')],
            current=selected,on_change=lambda key:self.set_canvas(*PRESETS[key]) if key in PRESETS else None)
        panel.append(PropertySection('Wallpaper size',picker))
        self.canvas_width=TextField('Width',value=str(self.width),purpose='number',
            on_activate=lambda *_:self.apply_dimensions())
        self.canvas_height=TextField('Height',value=str(self.height),purpose='number',
            on_activate=lambda *_:self.apply_dimensions())
        for field in (self.canvas_width,self.canvas_height):
            field.entry.set_width_chars(5); field.entry.set_max_width_chars(5)
        line=Gtk.Box(spacing=12,homogeneous=True)
        for field in (self.canvas_width,self.canvas_height): field.set_hexpand(True); line.append(field)
        panel.append(PropertySection('Exact dimensions',line))
        actions=box(6)
        for title,icon,callback in [('Apply dimensions','check',self.apply_dimensions),('Rotate size','rotate-cw',lambda:self.set_canvas(self.height,self.width)),
                                    ('Arrange displays','monitor',self.show_monitors)]:
            actions.append(TextButton(title,icon=icon,style='fill',small=True,on_click=callback))
        panel.append(PropertySection('Apply',actions)); return panel

    def show_size_presets(self):
        self.action_center.grow('size-presets',self.make_canvas_controls())

    def apply_dimensions(self):
        width=evaluate_number(self.canvas_width.entry.get_text())
        height=evaluate_number(self.canvas_height.entry.get_text())
        if width is None or height is None:
            self.error('Enter a width and height in pixels.'); return
        self.set_canvas(round(width),round(height))

    def set_canvas(self,width,height):
        try: dimensions(width,height)
        except ValueError as e: self.error(str(e)); self.sync_canvas(); return
        self.width,self.height=width,height; self.sync_canvas(); self.queue_preview()

    def sync_canvas(self):
        if not hasattr(self,'canvas_width'): return
        self.canvas_width.entry.set_text(str(self.width)); self.canvas_height.entry.set_text(str(self.height))

    def more_menu(self):
        rows=[]
        for title,icon,action in [('Save design','check',self.save),('Save a copy','copy',self.save_copy),
            ('Rename','pencil',self.rename),('Saved designs','folder-open',self.show_library),('Surprise me','shuffle',self.surprise)]:
            rows.append(MenuItem(title,icon=icon,on_activate=action))
        rows.append(None)
        if self.undo_stack: rows.append(MenuItem('Undo',icon='undo-2',on_activate=self.undo))
        if self.redo_stack: rows.append(MenuItem('Redo',icon='redo-2',on_activate=self.redo))
        rows.extend([MenuItem('Open recipe…',icon='folder-open',on_activate=self.import_recipe),
            MenuItem('Save recipe…',icon='share-2',on_activate=self.share_recipe),MenuItem('Export history',icon='history',on_activate=self.show_history)])
        return rows

    def rename(self):
        panel=self.panel_header('Name your design')
        self.name=PanelField('pencil','Design name',text=self.design.name,
            on_change=lambda text:self.change('name',text[:200]))
        self.name.entry.set_max_length(200)
        panel.append(self.name)
        panel.append(TextButton('Done',icon='check',small=True,style='fill',on_click=self.action_center.fold_panel))
        self.action_center.grow('rename',panel)

    def set_zoom(self,value):
        self.zoom_preview.zoom=max(.25,min(8.,value)); self.zoom_preview.queue_draw()
        if self.panel_key=='monitors': self.monitor_canvas.queue_draw()

    def zoom_by(self,direction): self.set_zoom(self.zoom_preview.zoom*(1.25**direction))

    def scroll_zoom(self,controller,dx,dy):
        if not controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK: return False
        if dy: self.zoom_by(-1 if dy>0 else 1)
        return True

    def position_begin(self,gesture,x,y):
        origin_x,origin_y,w,h=self.zoom_preview.fit_rect
        x-=origin_x; y-=origin_y
        scale=min(w/self.width,h/self.height)*self.zoom_preview.zoom
        image_w,image_h=self.width*scale,self.height*scale
        left,top=(w-image_w)/2,(h-image_h)/2
        self.drag_origin=None
        if not image_w or not image_h or not (left<=x<=left+image_w and top<=y<=top+image_h): return
        self.begin_gesture()
        self.drag_origin=(self.design.center_x,self.design.center_y,image_w,image_h)

    def position_move(self,gesture,dx,dy):
        if not getattr(self,'drag_origin',None): return
        x,y,w,h=self.drag_origin
        self.change('center_x',max(0,min(1,x+dx/w)))
        self.change('center_y',max(0,min(1,y+dy/h)))
        self.sync_controls()

    def reset_adjustments(self):
        self.checkpoint(); defaults=Design()
        for key,*_ in ADJUSTMENTS: setattr(self.design,key,getattr(defaults,key))
        self.sync_controls(); self.queue_preview()

    def load_thumbnails(self,jobs):
        self.thumbnail_jobs=[(self.thumbnail_epoch,*job) for job in jobs]
        self.next_thumbnail()

    def next_thumbnail(self):
        if self.closed or self.thumbnail_busy or not self.thumbnail_jobs: return
        epoch,picture,design,w,h=self.thumbnail_jobs.pop(0); self.thumbnail_busy=True
        future=self.thumbnail_pool.submit(pixels,design,w,h)
        def ready(f):
            try: data=f.result()
            except Exception: data=None
            GLib.idle_add(self.thumbnail_ready,epoch,picture,w,h,data)
        future.add_done_callback(ready)

    def thumbnail_ready(self,epoch,picture,w,h,data):
        self.thumbnail_busy=False
        if not self.closed and epoch==self.thumbnail_epoch and data is not None:
            if callable(picture): picture(data)
            else:
                texture=Gdk.MemoryTexture.new(w,h,Gdk.MemoryFormat.R8G8B8,GLib.Bytes.new(data.tobytes()),w*3)
                if isinstance(picture,MediaTile): picture.set_picture(texture)
                else: picture.set_paintable(texture)
        self.next_thumbnail(); return False

    def close_requested(self,*_):
        if self.exporting:
            Toast.show(self.host,'Cancel the export or wait for it to finish before closing.',kind='warning'); return True
        self.closed=True; self.thumbnail_jobs=[]
        if self.preview_timer: GLib.source_remove(self.preview_timer); self.preview_timer=0
        self.thumbnail_pool.shutdown(wait=False,cancel_futures=True)
        self.write_draft(); self.preview_pool.shutdown(wait=False,cancel_futures=True)
        self.export_pool.shutdown(wait=False,cancel_futures=True); return False

    def write_draft(self):
        try:
            p=self.library.root/'draft.json'; t=p.with_suffix('.tmp')
            from dataclasses import asdict
            t.write_text(json.dumps({'design':self.design.to_dict(),'canvas':[self.width,self.height],
                                     'monitors':[asdict(m) for m in self.monitors]})); t.replace(p)
        except OSError as e: self.status.set_label(f'Could not save draft: {e}')

    def set_color(self,index,rgba):
        color='#'+''.join(f'{round(v*255):02x}' for v in (rgba.red,rgba.green,rgba.blue))
        if color==self.design.colors[index]: return
        self.checkpoint(); self.design.colors=list(self.design.colors); self.design.colors[index]=color
        self.design.palette='Custom'; self.sync_controls(); self.queue_preview()
    def numeric_change(self,key,value):
        self.change(key,value); self.sync_controls()
    def begin_gesture(self):
        if not self.gesture_active: self.gesture_active=True; self.gesture_checkpoint=False
    def end_gesture(self): self.gesture_active=False; self.gesture_checkpoint=False

    def checkpoint(self):
        self.undo_stack.append(self.design.to_dict()); self.undo_stack=self.undo_stack[-100:]; self.redo_stack.clear()
    def change(self,key,value):
        if self.loading or getattr(self.design,key)==value: return
        if not self.gesture_active or not self.gesture_checkpoint:
            self.checkpoint(); self.gesture_checkpoint=True
        setattr(self.design,key,value)
        if key=='palette' and value in PALETTES: self.design.colors=list(PALETTES[value])
        if key in self.number_fields:
            field,factor=self.number_fields[key]; field.set_value(value*factor)
        self.queue_preview()

    def sync_controls(self):
        self.loading=True
        if self.panel_key=='rename': self.name.set_text(self.design.name)
        for key,(field,factor) in self.number_fields.items(): field.set_value(getattr(self.design,key)*factor)
        self.sync_canvas()
        if self.creation_key=='style':
            self.sync_choices(self.design.effect)
            self.thumbnail_epoch+=1
            self.load_thumbnails([(tile,replace(self.design,effect=effect),160,90) for effect,tile in self.choice_buttons.items()])
        if self.creation_key=='colors': self.set_creation_content('colors',self.colors_panel())
        for key,row in self.parameter_rows.items(): row.set_visible(adjustment_visible(key,self.design.effect))
        if self.creation_key=='edit-colors': self.refresh_color_swatches()
        self.loading=False

    def set_design(self,d,identity=None):
        # Opening a saved document starts its own undo history; never overwrite
        # that record with another document reached through Undo.
        if identity is not None: self.undo_stack.clear(); self.redo_stack.clear()
        else: self.checkpoint()
        self.design=d; self.design_id=identity; self.sync_controls(); self.queue_preview()
    def surprise(self): self.set_design(Design.surprise())
    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.design.to_dict()); self.design=Design.from_dict(self.undo_stack.pop()); self.sync_controls(); self.queue_preview()
    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.design.to_dict()); self.design=Design.from_dict(self.redo_stack.pop()); self.sync_controls(); self.queue_preview()
    def save(self):
        try:
            self.design_id=self.library.save(self.design,self.design_id); Toast.show(self.host,'Design saved',kind='saved')
        except Exception as e: self.error(str(e))
    def save_copy(self): self.design_id=None; self.save()
    def queue_preview(self):
        if self.closed: return
        self.revision+=1
        button=self.bar_anchor('size')
        resolution=f'{self.width:,} × {self.height:,}'
        button.bar_words.set_label(resolution); button.bar_item.label=resolution
        button.set_tooltip_text(f'{resolution} — adjust wallpaper size')
        button.update_property([Gtk.AccessibleProperty.LABEL],[f'{resolution}, adjust wallpaper size'])
        if self.panel_key=='monitors': self.monitor_canvas.queue_draw()
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
        if self.closed: return False
        # Present every completed frame during a drag, then render the latest state.
        # Rejecting intermediate revisions would starve the live preview.
        if error: self.status.set_label(error)
        else:
            data=GLib.Bytes.new(result.tobytes())
            texture=Gdk.MemoryTexture.new(w,h,Gdk.MemoryFormat.R8G8B8,data,w*3)
            self.picture.set_paintable(texture)
            if not self.exporting: self.status.set_label(f'{self.width:,} × {self.height:,}  ·  {self.design.effect}')
            if revision==self.revision: self.write_draft()
        if revision!=self.revision:
            self.start_preview()
        return False

    def error(self,message):
        d=Adw.AlertDialog(heading='Could not complete this action',body=message)
        d.add_response('ok','OK'); d.present(self)
    def edit_colors(self):
        panel=self.panel_header('Edit colors','Colors follow the gradient from its first color to its last.')
        self.color_flow=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,column_spacing=8,row_spacing=8,
                             min_children_per_line=2,max_children_per_line=8)
        swatches=self.color_flow
        self.color_swatches=[]; self.active_color=0
        for i,color in enumerate(self.design.colors):
            swatch=ColorSwatch(color,f'Color {i+1}: {color}',context=self.context)
            swatch.connect('clicked',lambda _,index=i:self.select_color(index))
            swatches.insert(swatch,-1); self.color_swatches.append(swatch)
        panel.append(swatches)
        self.color_well=LumaUI.ColorWell.new()
        self.color_well.update_property([Gtk.AccessibleProperty.LABEL],['Selected palette color'])
        self.color_well.connect('changed',self.color_well_changed)
        panel.append(self.color_well)
        panel.append(TextButton('Choose palette',icon='palette',small=True,style='fill',on_click=lambda:self.open_panel('colors')))
        self.set_creation_content('edit-colors',panel)
        self.select_color(0)

    def select_color(self,index):
        self.active_color=index
        for i,swatch in enumerate(self.color_swatches): swatch.set_active(i==index)
        rgba=Gdk.RGBA(); rgba.parse(self.design.colors[index])
        self.color_well.update_property([Gtk.AccessibleProperty.LABEL],[f'Color {index+1}'])
        previous=self.loading; self.loading=True; self.color_well.set_rgba(rgba); self.loading=previous

    def refresh_color_swatches(self):
        while self.color_flow.get_first_child(): self.color_flow.remove(self.color_flow.get_first_child())
        self.color_swatches=[]
        for i,color in enumerate(self.design.colors):
            swatch=ColorSwatch(color,f'Color {i+1}: {color}',context=self.context)
            swatch.connect('clicked',lambda _,index=i:self.select_color(index))
            self.color_flow.insert(swatch,-1); self.color_swatches.append(swatch)
        self.select_color(min(self.active_color,len(self.design.colors)-1))

    def color_well_changed(self,well):
        if self.loading: return
        self.set_color(self.active_color,well.get_rgba())

    def reverse_palette(self):
        self.checkpoint(); self.design.colors=list(reversed(self.design.colors)); self.design.palette='Custom'
        self.sync_controls(); self.queue_preview()

    def show_library(self):
        self.thumbnail_epoch+=1; self.thumbnail_jobs=[]
        panel=self.panel_header('Saved designs')
        panel.append(TextButton('Save a copy',icon='plus',style='fill',small=True,on_click=self.save_copy))
        rows=self.library.designs(); jobs=[]
        if not rows:
            panel.append(label('A place for your favorites. Save a design to return to it later.'))
        for identity,design,date in rows:
            thumb=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.COVER,width_request=64,height_request=40)
            panel.append(PanelRow(design.name or 'Untitled',lead=thumb,subtitle=design.effect,
                on_activate=lambda x=design,i=identity:self.set_design(x,i)))
            jobs.append((thumb,design,128,80))
        self.action_center.grow('library',panel); self.load_thumbnails(jobs)

    def show_history(self):
        self.thumbnail_epoch+=1; self.thumbnail_jobs=[]
        panel=self.panel_header('Export history'); rows=self.library.exports(); jobs=[]
        if not rows: panel.append(label('Your exported wallpapers will appear here. Each keeps its original design.'))
        for path,w,h,design,date in rows:
            panel.append(PanelHeading(design.name or 'Untitled'))
            thumb=Gtk.Picture(can_shrink=True,content_fit=Gtk.ContentFit.COVER,width_request=64,height_request=40)
            panel.append(PanelRow(f'{w:,} × {h:,}',lead=thumb,subtitle=f'{Path(path).name} · {date}',
                on_activate=lambda p=path:self.open_file(p)))
            panel.append(PanelRow('Use this design',icon='rotate-ccw',on_activate=lambda x=design:self.set_design(x)))
            jobs.append((thumb,design,128,80))
        self.action_center.grow('history',panel); self.load_thumbnails(jobs)

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

    def show_export(self):
        if self.exporting: self.show_export_progress(); return
        panel=box(0); self.export_depth=16
        precision=PropertyChoice('Color precision',[('8','8-bit'),('16','16-bit')],current='16',segments=True,
            on_change=lambda value:setattr(self,'export_depth',int(value)))
        note=label('8-bit works everywhere. 16-bit keeps more detail in smooth gradients.')
        apply_type(note,'caption')
        panel.append(PropertySection('PNG export',precision,note))
        actions=box(6)
        for title,icon,callback in [('Export wallpaper…','download',self.choose_export_location),
            ('Export a set…','images',lambda:self.show_batch(self.export_depth==16)),('Export for displays…','monitor',self.show_monitors)]:
            actions.append(TextButton(title,icon=icon,style='fill',small=True,on_click=callback))
        panel.append(PropertySection('Export',actions)); self.action_center.grow('export',panel)

    def choose_export_location(self):
        width,height=self.width,self.height; depth=self.export_depth
        try: dimensions(width,height)
        except ValueError as e: self.error(str(e)); return
        chooser=Gtk.FileDialog(title='Export wallpaper',initial_name=f'Aura-{width}x{height}.png')
        snapshot=Design.from_dict(self.design.to_dict())
        def selected(c,res):
            try: path=c.save_finish(res).get_path()
            except GLib.Error: return
            self.run_exports([(path,width,height,None)],depth,snapshot)
        chooser.save(self,None,selected)

    def show_export_progress(self):
        panel=self.panel_header('Exporting wallpaper','Keep designing while your wallpaper is saved.')
        self.export_bar=Gtk.ProgressBar(show_text=True)
        self.export_bar.set_fraction(getattr(self,'export_fraction',0)); panel.append(self.export_bar)
        panel.append(TextButton('Cancel export',icon='x',small=True,style='fill',on_click=self.cancel_event.set))
        self.action_center.grow('export-progress',panel)

    def show_batch(self,sixteen=True):
        panel=self.panel_header('Export a set','Each size is rendered separately. Existing exports stay safe.'); checks=[]
        for name,(w,h) in PRESETS.items():
            c=Gtk.CheckButton(label=f'{name}\n{w:,} × {h:,}'); checks.append((c,w,h)); panel.append(c)
        panel.append(label('A new uniquely named folder keeps existing exports safe.'))
        def start():
            sizes=[(w,h) for c,w,h in checks if c.get_active()]
            if not sizes: self.error('Choose at least one wallpaper size.'); return
            self.choose_folder(lambda folder:self.export_set(folder,sizes,16 if sixteen else 8))
        panel.append(TextButton('Choose folder and export…',icon='share',style='fill',small=True,on_click=start))
        self.action_center.grow('batch',panel)
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
        self.thumbnail_epoch+=1; self.thumbnail_jobs=[]
        panel=self.panel_header('Arrange displays','Drag the screens on the canvas. Match their sizes and positions to your desk.')
        previous=self.canvas_stack.get_child_by_name('monitors')
        if previous: self.canvas_stack.remove(previous)
        canvas=Gtk.DrawingArea(hexpand=True,vexpand=True)
        self.canvas_stack.add_named(canvas,'monitors')
        scroll=Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll',self.scroll_zoom); canvas.add_controller(scroll)
        canvas.update_property([Gtk.AccessibleProperty.LABEL],['Monitor arrangement preview. Exact positions can be edited below.'])
        rows=box(16); panel.append(rows); drawing={}; fields={}; dragging={}
        self.monitor_canvas=canvas; self.monitor_fields=fields
        background={}; render_size=[None]
        def image_ready(rgb):
            import cairo
            import numpy as np
            ph,pw=rgb.shape[:2]
            bgra=np.empty((ph,pw,4),dtype=np.uint8); bgra[:,:,:3]=rgb[:,:,::-1]; bgra[:,:,3]=255
            background['pixels']=bgra
            background['surface']=cairo.ImageSurface.create_for_data(bgra,cairo.FORMAT_ARGB32,pw,ph)
            canvas.queue_draw()
        summary=label(''); panel.append(summary)
        def describe():
            try:
                _,_,bw,bh=bounds(self.monitors)
                summary.set_label(f'Complete canvas · {bw:,} × {bh:,} pixels')
            except ValueError as e: summary.set_label(str(e))
        def draw(area,cr,w,h):
            try: x,y,bw,bh=bounds(self.monitors)
            except ValueError: return
            scale=min(max(1,w-32)/bw,max(1,h-32)/bh)*self.zoom_preview.zoom
            pw,ph=max(1,round(bw*scale)),max(1,round(bh*scale))
            size=(pw,ph,self.revision)
            if render_size[0]!=size:
                render_size[0]=size
                fit=min(1,860/pw,540/ph)
                self.load_thumbnails([(image_ready,Design.from_dict(self.design.to_dict()),max(1,round(pw*fit)),max(1,round(ph*fit)))])
            left=(w-pw)/2; top=(h-ph)/2
            drawing.update(x=x,y=y,scale=scale,left=left,top=top)
            for i,m in enumerate(self.monitors):
                xx=left+(m.x-x)*scale; yy=top+(m.y-y)*scale
                cr.save(); cr.rectangle(xx,yy,m.width*scale,m.height*scale); cr.clip()
                surface=background.get('surface')
                if surface is not None:
                    cr.translate(left,top); cr.scale(pw/surface.get_width(),ph/surface.get_height())
                    cr.set_source_surface(surface,0,0); cr.paint()
                cr.restore()
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
                for pair in ((('width','Width',1),('height','Height',1)),(('x','Left',-32000),('y','Top',-32000))):
                    line=Gtk.Box(spacing=12)
                    for key,title,lo in pair:
                        number=PropertyNumber(title,getattr(m,key),unit='px',minimum=lo,maximum=32000)
                        number.set_hexpand(True); number.update_property([Gtk.AccessibleProperty.LABEL],[f'Display {i+1} {key}'])
                        number.set_value(getattr(m,key)); fields[(id(m),key)]=number
                        number.connect('value-changed',lambda _,v,k=key,monitor=m:update(monitor,k,v)); line.append(number)
                    group.append(line)
                rows.append(group)
            describe(); canvas.queue_draw()
        drag=Gtk.GestureDrag(); self.monitor_drag=drag
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
        panel.append(TextButton('Add display',icon='plus',style='fill',small=True,on_click=add))
        panel.append(label('Screens snap to edges as you drag. Left and Top set exact positions; negative values place a screen left of or above the first.'))
        def layout_snapshot():
            layout=[replace(m) for m in self.monitors]; return layout,bounds(layout)
        def apply():
            try: layout,(_,_,w,h)=layout_snapshot()
            except ValueError as e: self.error(str(e)); return
            self.set_canvas(w,h); self.write_draft(); self.action_center.fold_panel()
        panel.append(TextButton('Use this wallpaper size',icon='check',style='fill',small=True,on_click=apply))
        def start():
            try: layout,(x,y,w,h)=layout_snapshot()
            except ValueError as e: self.error(str(e)); return
            self.set_canvas(w,h)
            def export(parent):
                folder=self.new_export_folder(parent)
                jobs=[(str(folder/'complete-span.png'),w,h,None)]
                jobs += [(str(folder/f'display-{i+1}.png'),m.width,m.height,(m.x-x,m.y-y,w,h)) for i,m in enumerate(layout)]
                self.run_exports(jobs,16)
            self.choose_folder(export)
        panel.append(TextButton('Export display wallpapers…',icon='share',style='fill',small=True,on_click=start))
        self.action_center.grow('monitors',panel)

    def run_exports(self,jobs,depth,design=None):
        if self.exporting: self.error('An export is already running.'); return
        self.exporting=True; self.cancel_event.clear(); self.export_fraction=0
        snapshot=design or Design.from_dict(self.design.to_dict())
        self.show_export_progress()
        def progress(value,index):
            def update():
                fraction=(index+value)/len(jobs); self.export_fraction=fraction
                self.export_bar.set_fraction(fraction); self.export_bar.set_text(f'{fraction:.0%}')
                self.status.set_label(f'Exporting · {fraction:.0%}'); return False
            GLib.idle_add(update)
        def work():
            complete=0; outcome='done'
            try:
                for i,(path,w,h,region) in enumerate(jobs):
                    export_png(snapshot,path,w,h,depth=depth,region=region,
                               progress=lambda v,index=i:progress(v,index),cancel=self.cancel_event)
                    self.library.record_export(path,w,h,snapshot); complete+=1
                message=f'Exported {complete} image'+('s' if complete!=1 else '')
            except Cancelled: message=f'Export cancelled · {complete} completed images kept'; outcome='warning'
            except Exception as e: message=f'Export failed: {e}'; outcome='error'
            GLib.idle_add(finish,message,outcome)
        def finish(message,outcome):
            self.exporting=False; self.status.set_label(message)
            if self.action_center.grown=='export-progress': self.action_center.fold_panel()
            Toast.show(self.host,message,kind=outcome); return False
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
