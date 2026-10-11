import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib
import numpy as np
from aura.model import Design, EFFECTS, PRESETS, Monitor, bounds, dimensions
from aura.render import pixels, export_png, Cancelled
from aura.store import Library

class EngineTests(unittest.TestCase):
    def test_all_effects_are_finite_and_different(self):
        hashes=set()
        for effect in EFFECTS:
            p=pixels(Design(effect=effect),140,80,depth=16)
            self.assertEqual(p.shape,(80,140,3)); self.assertGreater(p.std(),1000)
            hashes.add(p.tobytes())
        self.assertEqual(len(hashes),len(EFFECTS))
    def test_strips_are_identical(self):
        for effect in EFFECTS:
            d=Design(effect=effect)
            whole=pixels(d,101,83)
            pieces=np.concatenate([pixels(d,101,83,y,min(7,83-y)) for y in range(0,83,7)])
            np.testing.assert_array_equal(whole,pieces)
    def test_monitor_seams_are_exact(self):
        d=Design(effect='Fluted')
        whole=pixels(d,160,80)
        left=pixels(d,75,80,region=(0,0,160,80))
        right=pixels(d,85,80,region=(75,0,160,80))
        np.testing.assert_array_equal(whole,np.concatenate([left,right],axis=1))
    def test_png_crc_samples_and_precision(self):
        with tempfile.TemporaryDirectory() as tmp:
            for depth in (8,16):
                path=Path(tmp)/'out.png'; d=Design()
                export_png(d,path,31,23,depth=depth)
                data=path.read_bytes(); self.assertEqual(data[:8],b'\x89PNG\r\n\x1a\n')
                offset=8; compressed=b''; metadata=None
                while offset<len(data):
                    n=struct.unpack('!I',data[offset:offset+4])[0]; tag=data[offset+4:offset+8]; payload=data[offset+8:offset+8+n]
                    crc=struct.unpack('!I',data[offset+8+n:offset+12+n])[0]
                    self.assertEqual(crc,zlib.crc32(tag+payload)&0xffffffff)
                    if tag==b'IDAT': compressed+=payload
                    if tag==b'tEXt': metadata=json.loads(payload.split(b'\x00',1)[1])
                    offset+=n+12
                self.assertEqual(metadata,d.to_dict())
                expected=b''.join(b'\0'+r.tobytes() for r in pixels(d,31,23,depth=depth))
                self.assertEqual(zlib.decompress(compressed),expected)
    def test_cancel_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'out.png'; p.write_bytes(b'original'); cancel=threading.Event()
            with self.assertRaises(Cancelled):
                export_png(Design(),p,50,50,cancel=cancel,progress=lambda _:cancel.set())
            self.assertEqual(p.read_bytes(),b'original'); self.assertEqual(len(list(Path(tmp).iterdir())),1)
    def test_library_roundtrip_and_history_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib=Library(tmp); d=Design(); i=lib.save(d)
            lib.record_export('/tmp/image.png',16000,16000,d)
            d.name='Changed'; lib.save(d,i)
            self.assertEqual(len(lib.designs()),1); self.assertEqual(lib.designs()[0][1].name,'Changed')
            self.assertEqual(lib.exports()[0][3].name,'Untitled glow')
    def test_validation_and_layout(self):
        self.assertEqual(bounds([Monitor(100,200,-100,0),Monitor(200,100,0,40)]),(-100,0,300,200))
        for size in [(0,10),(32001,10),(32000,32000),(1.2,3)]:
            with self.assertRaises(ValueError): dimensions(*size)
        for change in [dict(softness=float('nan')),dict(seed=-1),dict(colors=['oops']),dict(version=2)]:
            with self.assertRaises(ValueError): Design(**change).validate()
        self.assertEqual(dimensions(16000,16000),(16000,16000))
        for preset in PRESETS.values():
            self.assertEqual(dimensions(*preset),preset)

    def test_rename_preserves_existing_library_draft_and_history(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'XDG_DATA_HOME': tmp}):
            data = Path(tmp)
            self.assertEqual(Library().root, data/'aura')
            (data/'aura/library.sqlite3').unlink()
            (data/'aura').rmdir()
            legacy = Library(data/'wally')
            design = Design(name='Saved before the rename')
            legacy.save(design)
            legacy.record_export('wallpaper.png', 3840, 2160, design)
            draft = json.dumps({'design': design.to_dict(), 'canvas': [3840, 2160]})
            (legacy.root/'draft.json').write_text(draft)
            renamed = Library()
            self.assertEqual(renamed.root, legacy.root)
            self.assertEqual(renamed.designs()[0][1].name, design.name)
            self.assertEqual(renamed.exports()[0][3].to_dict(), design.to_dict())
            self.assertEqual((renamed.root/'draft.json').read_text(), draft)
            explicit = Library(data/'aura')
            explicit.save(Design(name='New Aura library'))
            self.assertEqual(Library().designs()[0][1].name, 'New Aura library')
            self.assertEqual(legacy.designs()[0][1].name, design.name)

if __name__=='__main__': unittest.main()
