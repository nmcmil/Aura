"""Local SQLite library; completed exports keep an immutable recipe snapshot."""
import json
import os
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager
from .model import Design

class Library:
    def __init__(self, root=None):
        if root is None:
            data_home = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
            root = data_home/'aura'
            legacy_root = data_home/'wally'
            if not root.exists() and (legacy_root/'library.sqlite3').is_file():
                root = legacy_root
        self.root = Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'library.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS designs (id TEXT PRIMARY KEY, name TEXT, recipe TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP)')
            db.execute('CREATE TABLE IF NOT EXISTS exports (id TEXT PRIMARY KEY, path TEXT, width INTEGER, height INTEGER, recipe TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)')
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()
    def save(self,design,identity=None):
        design.validate(); identity=identity or uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO designs(id,name,recipe) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,recipe=excluded.recipe,updated=CURRENT_TIMESTAMP',(identity,design.name,json.dumps(design.to_dict())))
        return identity
    def designs(self):
        with self.connect() as db: return [(i,Design.from_dict(json.loads(r)),t) for i,r,t in db.execute('SELECT id,recipe,updated FROM designs ORDER BY updated DESC,rowid DESC')]
    def record_export(self,path,width,height,design):
        with self.connect() as db: db.execute('INSERT INTO exports(id,path,width,height,recipe) VALUES(?,?,?,?,?)',(uuid.uuid4().hex,str(path),width,height,json.dumps(design.to_dict())))
    def exports(self):
        with self.connect() as db: return [(p,w,h,Design.from_dict(json.loads(r)),t) for p,w,h,r,t in db.execute('SELECT path,width,height,recipe,created FROM exports ORDER BY rowid DESC')]
