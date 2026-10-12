# Verification

Aura 0.1.0 was qualified on x86_64 Ubuntu24.04.5 with its bundled Python3.14,
NumPy2.5.4, GTK and LumaUI/AppKit dependencies. The AppImage ran without app
network access or a separate Luma installation.

- All eight engine tests passed, covering effects, strip equivalence, monitor
  seams, PNG precision/metadata, cancellation, persistence and Wally compatibility.
- 1024×576 exports at8-bit and16-bit passed independent PNG CRC/decode checks.
- Native panels retained a live preview at1880,1180,1024,500 and360px widths,
  including a360×420 short window.
- About version/author and the supplied application icon were verified.
- The native save dialog produced a640×36016-bit PNG that passed independent
  decoding and CRC validation.
- Source/wheel builds, isolated wheel installation and dependency checks passed.

Native layout checks used Xvfb/Cairo. The README is an actual Ubuntu/Xfwm4
composited desktop capture with normal GTK rendering, dark appearance and Prism.
The visible1180×760 window is centered in a1340×920 capture with80px margins.
This qualification does not cover every Linux distribution, Wayland/GPU
configuration, architecture, screen reader or right-to-left visual layout.

## Reproduce engine checks

Use an isolated environment with Python and NumPy:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -p test_engine.py -v
mkdir -p verification-output
.venv/bin/python -m aura --export verification-output/example.png --width 1024 --height 576 --depth 16
.venv/bin/python tests/verify_large_png.py verification-output/example.png
```

Native fixtures tests/runtime_check.py and tests/interaction_check.py require
a qualified GTK/LumaUI/AppKit environment. Run them with disposable XDG data,
config, state and cache directories; never use a real design library for tests.
Headless engine checks alone do not validate the native interface.
