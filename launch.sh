#!/bin/bash
# Stable launcher wrapper for PolarTerm
# Fixes common "unstable" causes: Wayland vs X11, IBus, conda Qt
set -e
export DISPLAY="${DISPLAY:-:1}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_IM_MODULE=""
export NO_AT_BRIDGE=1
export QT_ACCESSIBILITY=1
# Use anaconda python if available, fallback to system
if [ -x "$HOME/anaconda3/bin/python3" ]; then
  PY="$HOME/anaconda3/bin/python3"
elif [ -x "$HOME/miniconda3/bin/python3" ]; then
  PY="$HOME/miniconda3/bin/python3"
else
  PY="python3"
fi
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="/tmp/polarterm.log"
echo "=== PolarTerm launch $(date) DISPLAY=$DISPLAY QT_QPA_PLATFORM=$QT_QPA_PLATFORM ===" >> "$LOG"
exec "$PY" -u "$APP_DIR/main.py" "$@" >> "$LOG" 2>&1
