#!/usr/bin/env bash
# CometBlue Control — installation script
# Usage: ./install.sh [--with-mcp] [--systemd] [--install-dir DIR]
set -e

INSTALL_DIR="${INSTALL_DIR:-/opt/cometblue-control}"
WITH_MCP=0
SETUP_SYSTEMD=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse args
for arg in "$@"; do
  case $arg in
    --with-mcp) WITH_MCP=1 ;;
    --systemd)  SETUP_SYSTEMD=1 ;;
    --install-dir=*) INSTALL_DIR="${arg#*=}" ;;
    --help|-h)
      echo "Usage: ./install.sh [--with-mcp] [--systemd] [--install-dir=DIR]"
      echo "  --with-mcp      Also install MCP server dependencies"
      echo "  --systemd       Install and enable systemd service (Linux)"
      echo "  --install-dir=  Target directory (default: /opt/cometblue-control)"
      exit 0
      ;;
  esac
done

echo "==> CometBlue Control Installer"
echo "    Install dir: $INSTALL_DIR"

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Please install Python 3.10+" >&2
  exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "    Python: $PY_VERSION"

# Copy files if running from a different directory
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ] && [ "$SETUP_SYSTEMD" -eq 1 ]; then
  echo "==> Copying files to $INSTALL_DIR"
  sudo mkdir -p "$INSTALL_DIR"
  sudo cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
  sudo chown -R "$(whoami)" "$INSTALL_DIR"
fi

TARGET="${SETUP_SYSTEMD:+$INSTALL_DIR}"
TARGET="${TARGET:-$SCRIPT_DIR}"

# Create venv
echo "==> Creating virtual environment at $TARGET/.venv"
python3 -m venv "$TARGET/.venv"
source "$TARGET/.venv/bin/activate"

# Install
echo "==> Installing cometblue-control..."
pip install --upgrade pip -q
if [ $WITH_MCP -eq 1 ]; then
  pip install -e "$TARGET[mcp]" -q
  echo "    Installed with MCP support"
else
  pip install -e "$TARGET" -q
  echo "    Installed (core + API + UI)"
fi

# Create user config dir — use the service user's actual home, not $HOME
# (differs when running via sudo without -H)
SERVICE_USER="$(whoami)"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" 2>/dev/null | cut -d: -f6 || echo "$HOME")"
CONFIG_DIR="$SERVICE_HOME/.cometblue"
mkdir -p "$CONFIG_DIR/profiles"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  cp "$TARGET/config/config.yaml" "$CONFIG_DIR/config.yaml"
  echo "==> Config created at $CONFIG_DIR/config.yaml"
fi

# Copy default profiles
for f in "$TARGET/config/profiles/"*.yaml; do
  dest="$CONFIG_DIR/profiles/$(basename "$f")"
  if [ ! -f "$dest" ]; then
    cp "$f" "$dest"
    echo "    Profile: $(basename "$f")"
  fi
done

# Setup systemd (Linux only)
if [ $SETUP_SYSTEMD -eq 1 ]; then
  if [ "$(uname)" != "Linux" ]; then
    echo "WARNING: --systemd is only supported on Linux, skipping"
  elif ! command -v systemctl &>/dev/null; then
    echo "WARNING: systemctl not found, skipping systemd setup"
  else
    echo "==> Installing systemd service"
    SERVICE_FILE="$TARGET/systemd/cometblue.service"
    # Replace %i placeholder with current user
    sudo bash -c "sed 's|%i|$SERVICE_USER|g; s|%h|$SERVICE_HOME|g; s|/opt/cometblue-control|$INSTALL_DIR|g' '$SERVICE_FILE' > /etc/systemd/system/cometblue.service"
    sudo systemctl daemon-reload
    sudo systemctl enable cometblue.service
    echo "    Service enabled. Start with: sudo systemctl start cometblue"
  fi
fi

echo ""
echo "==> Installation complete!"
echo ""
echo "    Start the server:"
echo "      source $TARGET/.venv/bin/activate"
echo "      cometblue-control serve"
echo ""
echo "    Web UI:  http://localhost:8080"
echo "    API docs: http://localhost:8080/docs"
if [ $WITH_MCP -eq 1 ]; then
  echo "    MCP:  cometblue-control mcp"
fi
echo ""
echo "    Config: $CONFIG_DIR/config.yaml"
