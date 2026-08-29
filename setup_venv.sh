#!/bin/bash
# PolarTerm - Universal setup for any system (Linux/macOS/Windows Git Bash)
# Works regardless of conflicting system packages like metadrive
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
echo "=== PolarTerm universal setup ==="
PY="python3"
if ! command -v python3 >/dev/null 2>&1; then
  PY="python"
fi
echo "Using: $($PY --version)"

# Create venv if not exists
if [ ! -d "venv" ]; then
  echo "Creating isolated venv (fixes pip resolver conflicts like metadrive)..."
  $PY -m venv venv
else
  echo "venv already exists, reusing..."
fi

echo "Activating venv and installing..."
# shellcheck disable=SC1091
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✓ Done. Installed in ./venv (isolated from system packages)."
echo "✓ Dark theme: auto-detected, toggle via View → Dark Mode"
echo "✓ HPC: timeout 20s, encrypted credentials"
echo ""
echo "Run: source venv/bin/activate && python main.py"
echo "  or: ./launch.sh  # auto-uses venv if present"
echo "  or: ./venv/bin/python main.py"
