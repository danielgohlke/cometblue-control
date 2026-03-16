#!/usr/bin/env bash
# CometBlue Control — Linux Installer (x86_64 / generic)
# Usage: ./install-linux.sh [--with-mcp] [--systemd] [--install-dir=DIR]
set -e

WITH_MCP=0
SETUP_SYSTEMD=0
INSTALL_DIR="/opt/cometblue-control"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for arg in "$@"; do
  case $arg in
    --with-mcp)       WITH_MCP=1 ;;
    --systemd)        SETUP_SYSTEMD=1 ;;
    --install-dir=*)  INSTALL_DIR="${arg#*=}" ;;
    --help|-h)
      echo "Usage: ./install-linux.sh [--with-mcp] [--systemd] [--install-dir=DIR]"
      echo "  --with-mcp        Also install MCP server dependencies"
      echo "  --systemd         Install and enable systemd service"
      echo "  --install-dir=    Target directory (default: /opt/cometblue-control)"
      exit 0 ;;
  esac
done

echo "==> CometBlue Control — Linux Installer"

if [ "$(uname)" != "Linux" ]; then
  echo "ERROR: This script is for Linux only." >&2
  exit 1
fi

# Verify source files are present
if [ ! -f "$SCRIPT_DIR/pyproject.toml" ]; then
  echo "ERROR: pyproject.toml not found in $SCRIPT_DIR" >&2
  echo "       Run this script from the cloned cometblue-control directory." >&2
  exit 1
fi

# Install system dependencies
if command -v apt-get &>/dev/null; then
  echo "==> Installing system packages (BlueZ, Python)..."
  sudo apt-get update -qq
  sudo apt-get install -y bluetooth bluez python3 python3-venv python3-pip
elif command -v dnf &>/dev/null; then
  echo "==> Installing system packages..."
  sudo dnf install -y bluez python3 python3-virtualenv
elif command -v pacman &>/dev/null; then
  echo "==> Installing system packages..."
  sudo pacman -S --noconfirm bluez python python-virtualenv
else
  echo "WARNING: Unknown package manager — make sure BlueZ and Python 3.10+ are installed."
fi

# Bluetooth service
echo "==> Enabling Bluetooth service..."
sudo systemctl enable bluetooth
sudo systemctl start bluetooth

# Add user to bluetooth group
if ! groups "$(whoami)" | grep -q bluetooth; then
  echo "==> Adding $(whoami) to bluetooth group..."
  sudo usermod -aG bluetooth "$(whoami)"
  echo "    NOTE: Log out and back in for group membership to take effect."
fi

# Check Python version
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "    Python: $PY_VERSION"
if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
  echo "ERROR: Python 3.10+ required." >&2; exit 1
fi

# Copy files
echo "==> Installing to $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
sudo rm -rf "$INSTALL_DIR/.venv" "$INSTALL_DIR/.git"
sudo chown -R "$(whoami)" "$INSTALL_DIR"
echo "    Files copied."

# venv + pip
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

# Config
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

# systemd service
if [ $SETUP_SYSTEMD -eq 1 ]; then
  echo "==> Installing systemd service..."
  SERVICE_SRC="$INSTALL_DIR/systemd/cometblue.service"
  sudo bash -c "sed 's|%i|$(whoami)|g; s|/opt/cometblue-control|$INSTALL_DIR|g' '$SERVICE_SRC' > /etc/systemd/system/cometblue.service"
  sudo systemctl daemon-reload
  sudo systemctl enable cometblue.service
  sudo systemctl start cometblue.service
  echo "    Service started. Status: sudo systemctl status cometblue"
  echo "    Logs:   journalctl -u cometblue -f"
fi

echo ""
echo "==> Installation complete!"
echo ""
if [ $SETUP_SYSTEMD -eq 0 ]; then
  echo "    Start manually:"
  echo "      source $INSTALL_DIR/.venv/bin/activate"
  echo "      cometblue-control serve"
fi
echo "    Web UI:   http://localhost:8080"
echo "    API docs: http://localhost:8080/docs"
echo "    Config:   $CONFIG_DIR/config.yaml"
echo ""
