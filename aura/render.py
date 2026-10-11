"""Analytic, strip-rendered sRGB PNG. Working memory is independent of height."""
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import zlib
import numpy as np
from .model import Design, dimensions

class Cancelled(Exception): pass

def _ramp(t, colors, softness):
    t = np.clip(t, 0, 1) * (len(colors)-1)
    i = np.minimum(t.astype(np.int32),len(colors)-2)
    f = t-i
    # Smooth interpolation keeps the supplied palette inside its RGB gamut.
    f = (1-softness)*f + softness*f*f*(3-2*f)
    return colors[i]*(1-f[...,None]) + colors[i+1]*f[...,None]

def pixels(design, width, height, y0=0, rows=None, *, region=None, depth=8):
    """Region coordinates use the complete span so monitor crops join exactly."""
    rows = height-y0 if rows is None else rows
    ox,oy,cw,ch = region or (0,0,width,height)
    x = (np.arange(width,dtype=np.float64)[None,:]+ox+.5)/cw
    y = (np.arange(y0,y0+rows,dtype=np.float64)[:,None]+oy+.5)/ch
    dx,dy = x-design.center_x,y-design.center_y
    a = math.radians(design.angle)
    u,v = dx*math.cos(a)-dy*math.sin(a),dx*math.sin(a)+dy*math.cos(a)
    p = np.array([[int(c[i:i+2],16)/255 for i in (1,3,5)] for c in design.colors])
    if design.effect in ('Glow','Halo'):
        # Superellipse produces the rounded rectangular glows in the references.
        power = 2 + design.edge*4
        radius = ((abs(u)/(.55*design.scale+.12))**power + (abs(v)/(.55*design.scale+.12))**power)**(1/power)
        t = 1-radius if design.effect=='Glow' else 1-abs(radius-.58)*1.65
    elif design.effect=='Horizon':
        t = .5+v/(design.scale+.25)
    elif design.effect=='Mesh':
        t = .5 + .24*np.sin(u*4.6/design.scale + design.seed%17) + .24*np.cos(v*4.1/design.scale) + .12*np.sin((u+v)*6)
    elif design.effect=='Stripes':
        t = .5+.5*np.sin((u+.18*v)*math.pi*design.frequency)
    elif design.effect=='Waves':
        t = .5+.5*np.sin((v+.16*np.sin(u*6))*math.pi*(design.frequency/3))
    else:
        t = .5+v*.75+u*.35+.16*np.sin(u*6+v*3)
        t += .035*np.cos(u*math.pi*design.frequency*12)
    rgb = _ramp(t,p,design.softness)
    if design.effect not in ('Glow','Halo'):
        rim = np.clip((np.maximum(abs(dx)*2,abs(dy)*2)-.62)/.55,0,1)
        rgb *= (1-design.edge*.32*rim[...,None])
    # Coordinate hash: reproducible regardless of strip boundaries or crop.
    xx = np.arange(width,dtype=np.uint32)[None,:] + np.uint32(ox)
    yy = np.arange(y0,y0+rows,dtype=np.uint32)[:,None] + np.uint32(oy)
    h = xx*np.uint32(374761393) + yy*np.uint32(668265263) + np.uint32(design.seed)
    h = (h ^ (h >> 13))*np.uint32(1274126177)
    noise = ((h ^ (h >> 16)).astype(np.float64)/4294967295-.5)
    maximum = 255 if depth==8 else 65535
    rgb += noise[...,None]*(design.grain*.12 + 1/maximum)
    return np.rint(np.clip(rgb,0,1)*maximum).astype(np.uint8 if depth==8 else '>u2')

def export_png(design, path, width, height, *, depth=16, region=None, progress=None, cancel=None, strip_rows=24):
    design.validate(); dimensions(width,height)
    if depth not in (8,16): raise ValueError('PNG depth must be 8 or 16')
    if not 1 <= strip_rows <= 256: raise ValueError('Invalid strip height')
    if region:
        ox,oy,cw,ch=region
        dimensions(cw,ch)
        if min(ox,oy)<0 or ox+width>cw or oy+height>ch: raise ValueError('Crop is outside canvas')
    path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix='.aura-',suffix='.part',dir=path.parent)
    def chunk(f,tag,data):
        f.write(struct.pack('!I',len(data))+tag+data+struct.pack('!I',zlib.crc32(tag+data)&0xffffffff))
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n')
            chunk(f,b'IHDR',struct.pack('!IIBBBBB',width,height,depth,2,0,0,0))
            chunk(f,b'sRGB',b'\x00')
            chunk(f,b'tEXt',b'Aura recipe\x00'+json.dumps(design.to_dict(),ensure_ascii=True).encode('ascii'))
            compressor=zlib.compressobj(3)
            for y in range(0,height,strip_rows):
                if cancel and cancel.is_set(): raise Cancelled('Export cancelled')
                image=pixels(design,width,height,y,min(strip_rows,height-y),region=region,depth=depth)
                for row in image:
                    data=compressor.compress(b'\x00'+row.tobytes())
                    if data: chunk(f,b'IDAT',data)
                if progress: progress(min(1,(y+len(image))/height))
            chunk(f,b'IDAT',compressor.flush())
            chunk(f,b'IEND',b'')
            f.flush(); os.fsync(f.fileno())
        if cancel and cancel.is_set(): raise Cancelled('Export cancelled')
        os.replace(tmp,path)
    except BaseException:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise
    return path
