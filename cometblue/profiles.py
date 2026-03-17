"""Profile management — load, save, apply heating profiles."""

from __future__ import annotations

import logging
from datetime import time
from pathlib import Path
from typing import Optional

import yaml

from .protocol import DaySchedule, TimePeriod, DAY_NAMES

log = logging.getLogger(__name__)

# Search order for profiles directory
_PROFILE_DIRS = [
    Path.home() / ".cometblue" / "profiles",
    Path(__file__).parent.parent / "config" / "profiles",
]


def _profiles_dir() -> Path:
    """Return first existing profiles directory, or create the user one."""
    for d in _PROFILE_DIRS:
        if d.exists():
            return d
    _PROFILE_DIRS[0].mkdir(parents=True, exist_ok=True)
    return _PROFILE_DIRS[0]


def list_profiles() -> list[str]:
    d = _profiles_dir()
    return [p.stem for p in sorted(d.glob("*.yaml"))]


def load_profile(name: str) -> dict:
    d = _profiles_dir()
    path = d / f"{name.lower()}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Profile '{name}' not found in {d}")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_profile(name: str, data: dict):
    d = _profiles_dir()
    path = d / f"{name.lower()}.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    log.info("Profile '%s' saved to %s", name, path)


def delete_profile(name: str):
    d = _profiles_dir()
    path = d / f"{name.lower()}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Profile '{name}' not found")
    path.unlink()
    log.info("Profile '%s' deleted", name)


def profile_to_schedules(profile: dict) -> dict[str, DaySchedule]:
    """Convert a profile's schedule definition to DaySchedule objects."""
    raw_schedules = profile.get("schedules", {})
    result: dict[str, DaySchedule] = {}

    for day in DAY_NAMES:
        raw = raw_schedules.get(day, [])
        periods = []
        for entry in raw:
            start = _parse_time(entry.get("start"))
            end = _parse_time(entry.get("end"))
            periods.append(TimePeriod(start=start, end=end))
        # Pad to 4 periods
        while len(periods) < 4:
            periods.append(TimePeriod())
        result[day] = DaySchedule(periods=periods[:4])

    return result


def _parse_time(t: Optional[str]) -> Optional[time]:
    if not t:
        return None
    try:
        parts = t.split(":")
        return time(int(parts[0]), int(parts[1]))
    except Exception:
        return None


async def apply_profile(
    name: str,
    device_addresses: list[str],
    apply_schedules: bool = True,
    adapter: Optional[str] = None,
) -> dict[str, str]:
    """
    Apply a profile to the given devices.
    Returns a dict of address → "ok" or error message.
    """
    from .device import CometBlueDevice
    from . import database as db

    profile = load_profile(name)
    results = {}

    for address in device_addresses:
        device_cfg = await db.get_device(address)
        pin = device_cfg.get("pin") if device_cfg else None

        try:
            status = await db.get_status(address)
            cached_offset = (status or {}).get("temp_offset") or 0.0
            mac_address = device_cfg.get("mac_address") if device_cfg else None
            _adapter = adapter or (device_cfg.get("adapter") if device_cfg else None)

            async with CometBlueDevice(address, pin=pin, mac_address=mac_address, adapter=_adapter) as dev:
                # Set temperatures
                await dev.set_temperatures(
                    comfort=profile.get("comfort_temp"),
                    eco=profile.get("eco_temp"),
                    offset=cached_offset,
                )

                # Apply child lock if defined in profile
                child_lock = profile.get("child_lock")
                if child_lock is not None:
                    await dev.set_child_lock(bool(child_lock))

                # Apply weekly schedules if requested
                if apply_schedules and "schedules" in profile:
                    schedules = profile_to_schedules(profile)
                    for i, day_name in enumerate(DAY_NAMES, start=1):
                        if day_name in schedules:
                            await dev.set_day_schedule(i, schedules[day_name])

            results[address] = "ok"
            log.info("Profile '%s' applied to %s", name, address)
        except Exception as e:
            results[address] = str(e)
            log.error("Failed to apply profile '%s' to %s: %s", name, address, e)

    return results
