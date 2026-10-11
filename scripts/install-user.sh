#!/bin/sh
# Installs only Aura and its isolated Python runtime into this user's home.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
runtime="$data_home/aura-runtime"
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("LumaUI", "1"); from gi.repository import Gtk, Adw, LumaUI; import cairo; from luma_appkit import AppWindow, NumericField, ColorSwatch'
python3 -m venv --system-site-packages "$runtime"
"$runtime/bin/python" -m pip install "$source_dir"
mkdir -p "$HOME/.local/bin" "$data_home/applications" "$data_home/icons/hicolor/scalable/apps"
cat > "$HOME/.local/bin/aura" <<EOF
#!/bin/sh
exec "$runtime/bin/aura" "\$@"
EOF
chmod +x "$HOME/.local/bin/aura"
sed "s|^Exec=.*|Exec=$HOME/.local/bin/aura|" "$source_dir/data/io.github.nmcmil.Aura.desktop" > "$data_home/applications/io.github.nmcmil.Aura.desktop"
cp "$source_dir/data/io.github.nmcmil.Aura.svg" "$data_home/icons/hicolor/scalable/apps/"
command -v update-desktop-database >/dev/null && update-desktop-database "$data_home/applications" || true
printf 'Aura installed. Launch it from the application menu or ~/.local/bin/aura\n'
