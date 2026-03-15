"""Configuration loading from config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import yaml

_DEFAULT_CONFIG_PATH = Path.home() / ".cometblue" / "config.yaml"
_PROJECT_CONFIG = Path(__file__).parent.parent / "config" / "config.yaml"

_DEFAULT = {
    "host": "0.0.0.0",
    "port": 8080,
    "poll_interval": 300,   # seconds
    "bluetooth": {
        "adapter": None,    # None = system default
        "scan_timeout": 10,
    },
    "ui": {
        "enabled": True,
    },
    "mcp": {
        "enabled": False,
    },
    "log_level": "INFO",
}

_config: dict = {}


def load(path: Optional[Path] = None) -> dict:
    global _config
    candidates = [
        path,
        _DEFAULT_CONFIG_PATH,
        _PROJECT_CONFIG,
    ]
    for p in candidates:
        if p and Path(p).exists():
            with open(p) as f:
                user = yaml.safe_load(f) or {}
            _config = _merge(_DEFAULT.copy(), user)
            return _config

    _config = _DEFAULT.copy()
    return _config


def get() -> dict:
    if not _config:
        load()
    return _config


def _merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _merge(base[k], v)
        else:
            base[k] = v
    return base
