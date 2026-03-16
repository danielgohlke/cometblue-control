#!/usr/bin/env bash
# CometBlue Control — Raspberry Pi Installer (armhf / arm64)
#
# ⚠️  ALPHA: Raspberry Pi support is functional but may require occasional
#     service restarts due to BlueZ/dbus-fast compatibility issues.
#
# Tested on: Raspberry Pi 3B+, 4B — Raspberry Pi OS (Bookworm/Bullseye)
# Usage: ./install-raspberry.sh [--with-mcp] [--install-dir=DIR]
set -e

WITH_MCP=0
INSTALL_DIR="/opt/cometblue-control"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="$(whoami)"

for arg in "$@"; do
  case $arg in
    --with-mcp)       WITH_MCP=1 ;;
    --install-dir=*)  INSTALL_DIR="${arg#*=}" ;;
    --help|-h)
      echo "Usage: ./install-raspberry.sh [--with-mcp] [--install-dir=DIR]"
      echo "  --with-mcp        Also install MCP server dependencies"
      echo "  --install-dir=    Target directory (default: /opt/cometblue-control)"
      exit 0 ;;
  esac
done

echo "==> CometBlue Control — Raspberry Pi Installer"
echo "    ⚠️  Raspberry Pi support is ALPHA — expect occasional BLE issues"
echo ""

if [ "$(uname)" != "Linux" ]; then
  echo "ERROR: This script is for Raspberry Pi (Linux) only." >&2
  exit 1
fi

# Verify source files are present
if [ ! -f "$SCRIPT_DIR/pyproject.toml" ]; then
  echo "ERROR: pyproject.toml not found in $SCRIPT_DIR" >&2
  echo "       Run this script from the cloned cometblue-control directory." >&2
  exit 1
fi

# System packages
echo "==> Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
  bluetooth bluez \
  python3 python3-venv python3-pip \
  rfkill

# Fix rfkill soft-block (common on Pi)
echo "==> Unblocking Bluetooth (rfkill)..."
sudo rfkill unblock bluetooth 2>/dev/null || true

# Ensure Bluetooth auto-enables on boot
if ! grep -q "^AutoEnable=true" /etc/bluetooth/main.conf 2>/dev/null; then
  echo "==> Setting AutoEnable=true in /etc/bluetooth/main.conf..."
  sudo sed -i '/^\[Policy\]/a AutoEnable=true' /etc/bluetooth/main.conf 2>/dev/null || \
    echo "AutoEnable=true" | sudo tee -a /etc/bluetooth/main.conf >/dev/null
fi

# Enable and start Bluetooth
sudo systemctl enable bluetooth
sudo systemctl restart bluetooth
sleep 2

# Verify Bluetooth is powered on
if command -v bluetoothctl &>/dev/null; then
  BT_STATE=$(bluetoothctl show 2>/dev/null | grep "Powered:" | awk '{print $2}')
  if [ "$BT_STATE" != "yes" ]; then
    echo "WARNING: Bluetooth may not be powered on. Try: sudo bluetoothctl power on"
  else
    echo "    Bluetooth: powered on ✓"
  fi
fi

# Add user to bluetooth group
if ! groups "$SERVICE_USER" | grep -q bluetooth; then
  echo "==> Adding $SERVICE_USER to bluetooth group..."
  sudo usermod -aG bluetooth "$SERVICE_USER"
fi

# Check Python
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "    Python: $PY_VERSION"
if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
  echo "ERROR: Python 3.10+ required. On older Pi OS, use:"
  echo "  sudo apt install python3.11 python3.11-venv"
  exit 1
fi

# Copy files
echo "==> Installing to $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
sudo rm -rf "$INSTALL_DIR/.venv" "$INSTALL_DIR/.git"
sudo chown -R "$SERVICE_USER" "$INSTALL_DIR"
echo "    Files copied."

# venv
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

# Pi-specific config recommendations
echo ""
echo "==> Applying Raspberry Pi recommended settings..."
# Set poll_interval to 600s if still at default 300s (Pi 3B+ needs more time per device)
if grep -q "poll_interval: 300" "$CONFIG_DIR/config.yaml"; then
  sed -i 's/poll_interval: 300/poll_interval: 600/' "$CONFIG_DIR/config.yaml"
  echo "    poll_interval set to 600s (Pi 3B+ needs ~45s per device)"
fi

# systemd service (always on Pi)
echo "==> Installing systemd service..."
SERVICE_SRC="$INSTALL_DIR/systemd/cometblue.service"
sudo bash -c "sed 's|%i|$SERVICE_USER|g; s|/opt/cometblue-control|$INSTALL_DIR|g' '$SERVICE_SRC' > /etc/systemd/system/cometblue.service"
sudo systemctl daemon-reload
sudo systemctl enable cometblue.service
sudo systemctl start cometblue.service

echo ""
echo "==> Installation complete!"
echo ""
echo "    Service:  sudo systemctl status cometblue"
echo "    Logs:     journalctl -u cometblue -f"
echo "    Web UI:   http://$(hostname -I | awk '{print $1}'):8080"
echo "    Config:   $CONFIG_DIR/config.yaml"
echo ""
echo "    ⚠️  ALPHA notes:"
echo "    - Each device takes ~45s to poll on Pi 3B+ (GATT service discovery)"
echo "    - If BLE stops working: sudo systemctl restart cometblue"
echo "    - If Bluetooth is blocked: sudo rfkill unblock bluetooth"
echo ""
