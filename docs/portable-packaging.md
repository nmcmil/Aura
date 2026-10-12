# Packaging

The primary x86_64 download is a self-contained AppImage. It bundles Python,
NumPy, GTK, libadwaita, LumaUI/AppKit, Figtree, introspection data and icon themes.
It uses its own ELF loader and does not install platform libraries on the host.
Dependency notices are included in the artifact.

## Build an AppImage

Supply qualified Luma Platform44 runtime files and the application files from
its Flatpak build, with Aura0.1.0 and the CPython3.14 NumPy wheel installed.
Build outputs must be separate from source and user data.

```sh
python3 scripts/build-portable.py --runtime-files /ABS/platform/files --app-files /ABS/aura-build/files --output /ABS/portable
curl -fL -o /ABS/runtime-x86_64 https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64
python3 scripts/build-appimage.py --portable-dir /ABS/portable/Aura --runtime /ABS/runtime-x86_64 --output /ABS/appimage
```

The builder computes the native dependency closure and verifies the AppImage
runtime SHA256 before use. A changed upstream runtime fails verification.
It uses two compression workers. The packaged runtime includes a FUSE-free
`--appimage-extract-and-run` fallback.

## Alternative Flatpak

The Flatpak targets org.projectluma.Platform/org.projectluma.Sdk branch44.
Prepare hash-sealed wheels with scripts/prepare-flatpak.py and build the staged
manifest with flatpak-builder. This format downloads a separate Luma runtime.
The installed Flatpak passed native/engine checks on a qualified Luma runtime;
Ubuntu Flatpak qualification has not been completed. The AppImage is the primary
release download. See verification.md for observed portable qualification.

Packaging does not grant a license for Aura. Dependencies retain their own
licenses and notices; see provenance.md.
