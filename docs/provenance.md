# Provenance

Aura was formerly Wally. The application, procedural effects, PNG encoder,
persistence code and tests are project code. The application icon is supplied
artwork, preserved byte-for-byte.

| Dependency | Use | License/notices |
| --- | --- | --- |
| NumPy | Pixel evaluation | BSD-3-Clause |
| Python | Runtime and standard library | Python license |
| GTK, libadwaita, PyGObject, pycairo | Native interface | Existing upstream notices |
| LumaUI/AppKit | Native components and appearance | Existing platform notices |
| Figtree and icon themes | Native typography and icons | Existing font/theme notices |

The portable artifact retains dependency notices. The upstream static AppImage
runtime is pinned to SHA256156f4bdbde9c52d01814600013e0a273f0118dc2de98975f3c8c63427ec79074;
its MIT and linked-library notices are preserved in
packaging/portable/appimage-runtime.LICENSE and in the artifact.

README imagery is an actual composited desktop screenshot. The app displays a
Poolside Fluted wallpaper, with the Luma Prism desktop background and native
window shadow. No standalone desktop wallpaper or toolkit binaries are stored
in this source repository.

No license grant is made for the original application code. Dependencies retain
their existing licenses; packaging does not replace them.
