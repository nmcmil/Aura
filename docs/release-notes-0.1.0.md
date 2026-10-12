# Aura 0.1.0

Aura is an independent wallpaper studio by nick ([@nmcmil](https://github.com/nmcmil)), formerly Wally.

- Native Luma creation controls, visible palette choices and a single scrolling adjustment column.
- Seven wallpaper styles, live preview, zoom, exact dimensions and desktop presets through8K.
- Main-canvas multi-display arrangements and seamless per-display exports.
- Full-resolution8-bit/16-bit PNG output, saved recipes/designs and export history.
- Existing Wally recipe schema and libraries retained.
- Updated icon and About Aura in the app menu.

Download **Aura-0.1.0-x86_64.AppImage** (71 MB). It includes Python, NumPy,
GTK, LumaUI/AppKit, Figtree and icon themes; no separate runtime download.
Mark it executable and open it. The app works offline.

Qualified in a disposable Ubuntu24.04.5 VM: installed-package engine tests,
independent8/16-bit PNG validation, native layout down to360px, and About/icon
checks. The README shows the native app in dark mode on a Prism desktop.
Headless X11 qualification does not cover every distribution, Wayland or GPU.
Source and Python wheel are included for development; the wheel alone needs
the native Luma platform dependencies.

Existing Aura/Wally data paths and recipe compatibility are retained.
No new application license is granted;
bundled dependencies retain their existing notices.
