"""Versioned, portable wallpaper recipes. No toolkit dependency."""
from dataclasses import dataclass, asdict, field
import math
import random

PALETTES = {
    'Afterglow': ['#08091f', '#2532dd', '#b334ed', '#fa55ad', '#ff991f'],
    'Poolside': ['#12284c', '#146dda', '#28c7df', '#e6e6c9', '#ff8549'],
    'Apricot': ['#35163b', '#bc385f', '#ef784b', '#ffc888', '#f7e9cf'],
    'Aurora': ['#101730', '#493786', '#9679cb', '#37bba9', '#b4efd7'],
    'Dusk': ['#162131', '#496682', '#9d9abc', '#e3b9cd', '#f6dfca'],
    'Electric': ['#070614', '#2013a2', '#4935fa', '#ed37b8', '#ff720e'],
    'Meadow': ['#153d3c', '#378a79', '#91b68e', '#dbdca8', '#f4daba'],
    'Porcelain': ['#657ba8', '#a9bbd2', '#e8edef', '#dcc5dc', '#bd83b0'],
}
EFFECTS = ('Glow', 'Halo', 'Horizon', 'Mesh', 'Stripes', 'Fluted', 'Waves')
PRESETS = {'Desktop · 4K': (3840, 2160), 'Ultrawide · 49 inch': (5120, 1440),
           'Ultrawide · dual 4K': (7680, 2160), 'Phone · portrait': (1290, 2796),
           'Tablet': (2048, 2732), 'Square · 16K': (16000, 16000)}

@dataclass
class Design:
    name: str = 'Untitled glow'
    effect: str = 'Glow'
    palette: str = 'Afterglow'
    colors: list[str] = field(default_factory=lambda: list(PALETTES['Afterglow']))
    softness: float = .65
    scale: float = .65
    angle: float = 0
    center_x: float = .5
    center_y: float = .48
    grain: float = .12
    edge: float = .85
    frequency: float = 8
    seed: int = 42
    version: int = 1

    def validate(self):
        if self.version != 1 or self.effect not in EFFECTS:
            raise ValueError('Unsupported recipe version or effect')
        if not isinstance(self.name, str) or len(self.name) > 200:
            raise ValueError('Design name is too long')
        if not 2 <= len(self.colors) <= 8:
            raise ValueError('Use two to eight colors')
        for color in self.colors:
            if not isinstance(color, str) or len(color) != 7 or color[0] != '#':
                raise ValueError('Colors must be #RRGGBB')
            int(color[1:], 16)
        for key, low, high in [('softness',0,1),('scale',.1,1.5),('angle',-180,180),
                               ('center_x',0,1),('center_y',0,1),('grain',0,1),
                               ('edge',0,1),('frequency',2,48)]:
            value = getattr(self,key)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'Invalid {key}')
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ValueError('Invalid random seed')
        return self

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Recipe must be an object')
        return cls(**value).validate()

    @classmethod
    def surprise(cls):
        palette = random.choice(list(PALETTES))
        return cls(name=f'{palette} study', effect=random.choice(EFFECTS), palette=palette,
                   colors=list(PALETTES[palette]), softness=random.uniform(.4,.85),
                   scale=random.uniform(.45,.9), angle=random.uniform(-35,35),
                   grain=random.uniform(.04,.2), seed=random.randrange(2**32))

@dataclass
class Monitor:
    width: int = 2560
    height: int = 1440
    x: int = 0
    y: int = 0
    name: str = 'Display'

    def validate(self):
        dimensions(self.width, self.height)
        if type(self.x) is not int or type(self.y) is not int or abs(self.x)>64000 or abs(self.y)>64000:
            raise ValueError('Invalid display position')
        return self

def dimensions(width, height):
    if type(width) is not int or type(height) is not int or not (1 <= width <= 32000 and 1 <= height <= 32000):
        raise ValueError('Dimensions must be whole pixels between 1 and 32,000')
    if width * height > 512_000_000:
        raise ValueError('Choose a canvas of at most 512 megapixels')
    return width, height

def bounds(monitors):
    if not 1 <= len(monitors) <= 8:
        raise ValueError('Use one to eight displays')
    for m in monitors: m.validate()
    x, y = min(m.x for m in monitors), min(m.y for m in monitors)
    w, h = max(m.x+m.width for m in monitors)-x, max(m.y+m.height for m in monitors)-y
    dimensions(w,h)
    return x,y,w,h
