#!/bin/bash
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP="$HOME/.local/share/applications/polarterm.desktop"
OLD_DESKTOP="$HOME/.local/share/applications/mobaxtreme.desktop"
mkdir -p "$(dirname "$DESKTOP")"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Name=PolarTerm
Comment=PolarTerm - HPC Terminal & File Manager (drag-drop, secure, penguin)
Exec=$APP_DIR/launch.sh
Icon=$APP_DIR/resources/polarterm.png
Terminal=false
Type=Application
Categories=Network;Utility;Development;
Keywords=ssh;sftp;polarterm;hpc;terminal;penguin;
StartupWMClass=PolarTerm
Path=$APP_DIR
EOF
chmod +x "$DESKTOP"
# remove old mobaxtreme desktops
rm -f "$OLD_DESKTOP" "$HOME/Desktop/mobaxtreme.desktop" 2>/dev/null || true
cp "$DESKTOP" "$HOME/Desktop/polarterm.desktop" 2>/dev/null || true
chmod +x "$HOME/Desktop/polarterm.desktop" 2>/dev/null || true
gio set "$HOME/Desktop/polarterm.desktop" metadata::trusted true 2>&1 || true
gio set "$DESKTOP" metadata::trusted true 2>&1 || true
update-desktop-database ~/.local/share/applications 2>&1 || true
echo "Desktop entry created at $DESKTOP"
echo "Launch via: $APP_DIR/launch.sh or search 'PolarTerm' in app grid"
