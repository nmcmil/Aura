"""Presentation names only; recipe keys and effect identities remain version 1."""
STYLE_NOTES = {
    'Glow': 'A soft pool of color',
    'Halo': 'A luminous ring',
    'Horizon': 'Color flowing across the horizon',
    'Mesh': 'Layers of flowing color',
    'Stripes': 'Repeating bands of color',
    'Fluted': 'Fine ridges with a glass-like finish',
    'Waves': 'Rolling ribbons of color',
}
# key, label, minimum, maximum, step, unit, display factor, page
ADJUSTMENTS = (
    ('softness', 'Color blending', 0, 1, .01, '%', 100, 'finish'),
    ('scale', 'Spread', .1, 1.5, .01, '%', 100, 'shape'),
    ('angle', 'Rotation', -180, 180, 1, '°', 1, 'shape'),
    ('center_x', 'Horizontal position', 0, 1, .01, '%', 100, 'position'),
    ('center_y', 'Vertical position', 0, 1, .01, '%', 100, 'position'),
    ('edge', 'Roundness', 0, 1, .01, '%', 100, 'shape'),
    ('frequency', 'Pattern density', 2, 48, 1, '', 1, 'shape'),
    ('grain', 'Grain', 0, 1, .01, '%', 100, 'finish'),
)


def adjustment_visible(key, effect):
    if key == 'scale':
        return effect in ('Glow', 'Halo', 'Horizon', 'Mesh')
    if key == 'frequency':
        return effect in ('Stripes', 'Fluted', 'Waves')
    return True
