#!/usr/bin/env bash
# CometBlue Control — macOS Installer
# Usage: ./install-macos.sh [--with-mcp] [--launchd]
set -e

WITH_MCP=0
SETUP_LAUNCHD=0
# No spaces in path — pip extras syntax "path[extra]" breaks with spaces
INSTALL_DIR="$HOME/.cometblue-control"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for arg in "$@"; do
  case $arg in
    --with-mcp)  WITH_MCP=1 ;;
    --launchd)   SETUP_LAUNCHD=1 ;;
    --help|-h)
      echo "Usage: ./install-macos.sh [--with-mcp] [--launchd]"
      echo "  --with-mcp   Also install MCP server dependencies"
      echo "  --launchd    Install as launchd agent (auto-start at login)"
      exit 0 ;;
  esac
done

echo "==> CometBlue Control — macOS Installer"
echo ""

# Check macOS
if [ "$(uname)" != "Darwin" ]; then
  echo "ERROR: This script is for macOS only." >&2
  exit 1
fi

# Verify source files are present
if [ ! -f "$SCRIPT_DIR/pyproject.toml" ]; then
  echo "ERROR: pyproject.toml not found in $SCRIPT_DIR" >&2
  echo "       Run this script from the cloned cometblue-control directory." >&2
  exit 1
fi

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found."
  echo "  Install via Homebrew: brew install python3"
  exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
echo "    Python: $PY_VERSION"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "ERROR: Python 3.10+ required (found $PY_VERSION)" >&2
  exit 1
fi

# Copy to install dir (exclude .venv and .git — they are recreated/irrelevant)
echo "==> Installing to: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
rm -rf "$INSTALL_DIR/.venv" "$INSTALL_DIR/.git"
echo "    Files copied."

# Create venv
echo "==> Creating virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"

pip install --upgrade pip

if [ $WITH_MCP -eq 1 ]; then
  pip install -e "$INSTALL_DIR[mcp]"
  echo "    Installed with MCP support"
else
  pip install -e "$INSTALL_DIR"
  echo "    Installed (core + API + UI)"
fi

# Create config dir and copy defaults
CONFIG_DIR="$HOME/.cometblue"
mkdir -p "$CONFIG_DIR/profiles"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  cp "$INSTALL_DIR/config/config.yaml" "$CONFIG_DIR/config.yaml"
  echo "==> Config created at $CONFIG_DIR/config.yaml"
fi

for f in "$INSTALL_DIR/config/profiles/"*.yaml; do
  dest="$CONFIG_DIR/profiles/$(basename "$f")"
  [ ! -f "$dest" ] && cp "$f" "$dest"
done
echo "    Profiles: $CONFIG_DIR/profiles/"

# macOS Bluetooth note
echo ""
echo "    NOTE: On first run, macOS will ask for Bluetooth permission."
echo "    Grant it in System Settings → Privacy & Security → Bluetooth."
echo ""

# LaunchAgent (optional auto-start at login)
if [ $SETUP_LAUNCHD -eq 1 ]; then
  PLIST_DIR="$HOME/Library/LaunchAgents"
  PLIST="$PLIST_DIR/de.gohlke.cometblue-control.plist"
  mkdir -p "$PLIST_DIR"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>de.gohlke.cometblue-control</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/.venv/bin/cometblue-control</string>
        <string>serve</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/.cometblue/cometblue.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.cometblue/cometblue.log</string>
</dict>
</plist>
PLIST
  launchctl load "$PLIST" 2>/dev/null || true
  echo "==> LaunchAgent installed — starts automatically at login"
  echo "    Stop:    launchctl unload $PLIST"
  echo "    Start:   launchctl load $PLIST"
  echo "    Logs:    tail -f ~/.cometblue/cometblue.log"
fi

echo ""
echo "==> Installation complete!"
echo ""
if [ $SETUP_LAUNCHD -eq 0 ]; then
  echo "    Start manually:"
  echo "      source \"$INSTALL_DIR/.venv/bin/activate\""
  echo "      cometblue-control serve"
  echo ""
  echo "    Or with auto-start: ./install-macos.sh --launchd"
fi
echo "    Web UI:   http://localhost:8080"
echo "    API docs: http://localhost:8080/docs"
echo "    Config:   $CONFIG_DIR/config.yaml"
echo ""
