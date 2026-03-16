#!/usr/bin/env bash
# CometBlue Control — Uninstaller
# Supports: macOS (launchd), Linux/Raspberry Pi (systemd), generic installs
#
# Usage: ./uninstall.sh [--purge] [--install-dir=DIR] [--yes]
#   --purge           Also delete ~/.cometblue (config, profiles, logs)
#   --install-dir=    Override install directory to remove
#   --yes             Skip confirmation prompts
set -e

PURGE=0
YES=0
OS="$(uname)"

# Default install dirs per platform
if [ "$OS" = "Darwin" ]; then
  INSTALL_DIR="$HOME/.cometblue-control"
else
  INSTALL_DIR="/opt/cometblue-control"
fi

CONFIG_DIR="$HOME/.cometblue"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/de.gohlke.cometblue-control.plist"
SYSTEMD_UNIT="/etc/systemd/system/cometblue.service"

# ── Parse args ──────────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --purge)          PURGE=1 ;;
    --yes|-y)         YES=1 ;;
    --install-dir=*)  INSTALL_DIR="${arg#*=}" ;;
    --help|-h)
      echo "Usage: ./uninstall.sh [--purge] [--install-dir=DIR] [--yes]"
      echo "  --purge           Also delete ~/.cometblue (config, profiles, logs)"
      echo "  --install-dir=    Override install directory (default: $INSTALL_DIR)"
      echo "  --yes             Skip confirmation prompts"
      exit 0 ;;
  esac
done

# ── Helpers ──────────────────────────────────────────────────────────────────
confirm() {
  [ "$YES" -eq 1 ] && return 0
  read -r -p "$1 [y/N] " ans
  case "$ans" in [yY]*) return 0 ;; *) return 1 ;; esac
}

echo "==> CometBlue Control — Uninstaller"
echo ""
echo "    Install dir : $INSTALL_DIR"
echo "    Config dir  : $CONFIG_DIR"
if [ "$PURGE" -eq 1 ]; then
  echo "    Mode        : PURGE (config will also be deleted)"
else
  echo "    Mode        : keep config (use --purge to also remove $CONFIG_DIR)"
fi
echo ""

confirm "Continue with uninstall?" || { echo "Aborted."; exit 0; }

# ── macOS: launchd ───────────────────────────────────────────────────────────
if [ "$OS" = "Darwin" ]; then
  if [ -f "$LAUNCHD_PLIST" ]; then
    echo "==> Stopping LaunchAgent..."
    launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    rm -f "$LAUNCHD_PLIST"
    echo "    Removed: $LAUNCHD_PLIST"
  else
    echo "    LaunchAgent not found (skipping)"
  fi
fi

# ── Linux: systemd ───────────────────────────────────────────────────────────
if [ "$OS" = "Linux" ] && command -v systemctl &>/dev/null; then
  if systemctl list-unit-files cometblue.service &>/dev/null 2>&1 | grep -q cometblue; then
    echo "==> Stopping and disabling systemd service..."
    sudo systemctl stop cometblue.service 2>/dev/null || true
    sudo systemctl disable cometblue.service 2>/dev/null || true
    echo "    Service stopped and disabled."
  else
    echo "    systemd service not found (skipping)"
  fi

  if [ -f "$SYSTEMD_UNIT" ]; then
    sudo rm -f "$SYSTEMD_UNIT"
    sudo systemctl daemon-reload
    echo "    Removed: $SYSTEMD_UNIT"
  fi
fi

# ── Remove install directory ─────────────────────────────────────────────────
if [ -d "$INSTALL_DIR" ]; then
  echo "==> Removing install directory: $INSTALL_DIR"
  if [ "$OS" = "Linux" ] && [[ "$INSTALL_DIR" == /opt/* ]]; then
    sudo rm -rf "$INSTALL_DIR"
  else
    rm -rf "$INSTALL_DIR"
  fi
  echo "    Done."
else
  echo "    Install directory not found: $INSTALL_DIR (skipping)"
fi

# ── Optionally remove config ──────────────────────────────────────────────────
if [ "$PURGE" -eq 1 ]; then
  if [ -d "$CONFIG_DIR" ]; then
    echo "==> Removing config directory: $CONFIG_DIR"
    rm -rf "$CONFIG_DIR"
    echo "    Done."
  else
    echo "    Config directory not found: $CONFIG_DIR (skipping)"
  fi
else
  echo ""
  echo "    Config kept at: $CONFIG_DIR"
  echo "    Run with --purge to also remove it."
fi

echo ""
echo "==> Uninstall complete."
echo ""
