"""Independently stream-decode PNG data without allocating the full image."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib
p=Path(sys.argv[1]); total=0; ihdr=None; decoder=zlib.decompressobj(); digest=hashlib.sha256()
with p.open('rb') as f:
    signature=f.read(8); assert signature==b'\x89PNG\r\n\x1a\n'; digest.update(signature)
    while True:
        header=f.read(8)
        if not header: break
        n,tag=struct.unpack('!I4s',header); payload=f.read(n); crc=f.read(4)
        assert len(payload)==n and zlib.crc32(tag+payload)&0xffffffff==struct.unpack('!I',crc)[0]
        digest.update(header+payload+crc)
        if tag==b'IHDR': ihdr=struct.unpack('!IIBBBBB',payload)
        if tag==b'IDAT': total+=len(decoder.decompress(payload))
        if tag==b'IEND': assert f.read()==b''; break
assert decoder.eof
w,h,depth,color,*_=ihdr
assert color==2 and total==h*(1+w*3*(depth//8))
print(json.dumps({'width':w,'height':h,'depth':depth,'decoded_bytes':total,'file_bytes':p.stat().st_size,'sha256':digest.hexdigest(),'crc_and_decode':'passed'},indent=2))
