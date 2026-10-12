# Flatpak packaging

Aura targets `org.projectluma.Platform` and `org.projectluma.Sdk`, branch 44, on x86_64. The package includes its Python wheel, CPython3.14 NumPy wheel, application metadata, screenshot and the settings schema used by Luma AppKit menus.

Build a wheel from the source checkout, then seal the inputs:

```sh
python3 -m build --wheel
python3 scripts/prepare-flatpak.py --aura-wheel dist/aura_wallpaper-0.1.1-py3-none-any.whl --numpy-wheel /path/to/numpy-cp314-x86_64.whl --output flatpak-inputs
flatpak-builder --user --disable-rofiles-fuse --default-branch=stable --repo=flatpak-repo flatpak-build flatpak-inputs/io.github.nmcmil.Aura.json
```

The helper checks identities and records source/file hashes. For a source archive, pass its exact Git commit with `--source-commit `. Install the signed Luma runtime and SDK before building.

The shell-state schema and Apache 2.0 license are copied unchanged from `SimplyLuma/luma`, commit `a0caacdf14fc6aeb6b27b858ed080dfbb2243a6a`. Including the schema prevents menu code from failing on a runtime without it. This does not change the system's schema or desktop settings.

Aura grants no network or home-wide access. File dialogs use desktop portals; Aura and legacy Wally design libraries retain their native data locations.
