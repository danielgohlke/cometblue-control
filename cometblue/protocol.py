"""BLE data encoding/decoding for CometBlue thermostats."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, date, time
from typing import Optional

# ── UUIDs ────────────────────────────────────────────────────────────────────
BASE = "47e9ee{:02x}-47e9-11e4-8939-164230d1df67"

UUID_DATETIME       = BASE.format(0x01)
UUID_FLAGS          = BASE.format(0x2A)
UUID_TEMPERATURES   = BASE.format(0x2B)
UUID_BATTERY        = BASE.format(0x2C)
UUID_FIRMWARE2      = BASE.format(0x2D)
UUID_LCD_TIMER      = BASE.format(0x2E)
UUID_PIN            = BASE.format(0x30)
UUID_DAY            = BASE.format(0x10)   # + index offset per handle
UUID_HOLIDAY        = BASE.format(0x20)   # + index offset per handle

# Standard BLE info service UUIDs
UUID_DEVICE_NAME        = "00002a00-0000-1000-8000-00805f9b34fb"
UUID_SYSTEM_ID          = "00002a23-0000-1000-8000-00805f9b34fb"
UUID_MODEL_NUMBER       = "00002a24-0000-1000-8000-00805f9b34fb"
UUID_FIRMWARE_REVISION  = "00002a26-0000-1000-8000-00805f9b34fb"
UUID_SOFTWARE_REVISION  = "00002a28-0000-1000-8000-00805f9b34fb"
UUID_MANUFACTURER_NAME  = "00002a29-0000-1000-8000-00805f9b34fb"

# Day UUIDs: Monday=1 → UUID_DAY_BASE+0, ..., Sunday=7 → UUID_DAY_BASE+6
_DAY_UUIDS = [BASE.format(0x10 + i) for i in range(7)]
_HOLIDAY_UUIDS = [BASE.format(0x20 + i) for i in range(8)]

UNCHANGED = 0x80  # Placeholder for "do not change this value"

SUPPORTED_MANUFACTURER = "eurotronic gmbh"
SUPPORTED_MODEL = "comet blue"


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Temperatures:
    current: Optional[float] = None       # Read-only (measured)
    manual: Optional[float] = None        # Manual setpoint
    comfort: Optional[float] = None       # Comfort (high) setpoint
    eco: Optional[float] = None           # Eco (low) setpoint
    offset: Optional[float] = None        # Temperature offset
    window_open: Optional[bool] = None    # Window open detection active
    window_minutes: Optional[int] = None  # Window open duration


@dataclass
class TimePeriod:
    """A heating on/off period within a day."""
    start: Optional[time] = None  # None = disabled
    end: Optional[time] = None    # None = disabled


@dataclass
class DaySchedule:
    """Up to 4 time periods for one day."""
    periods: list[TimePeriod] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "DaySchedule":
        return cls(periods=[TimePeriod() for _ in range(4)])


@dataclass
class Holiday:
    slot: int = 1
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    temperature: Optional[float] = None
    active: bool = False


# ── Encoding / Decoding ───────────────────────────────────────────────────────

def encode_pin(pin: int) -> bytes:
    """Encode PIN as 4-byte little-endian."""
    return struct.pack("<I", pin)


def decode_temperatures(data: bytes) -> Temperatures:
    """Decode 7-byte temperature characteristic."""
    if len(data) < 7:
        raise ValueError(f"Expected 7 bytes, got {len(data)}")
    vals = struct.unpack("7b", data)

    def _temp(v: int) -> Optional[float]:
        return None if v == UNCHANGED else v / 2.0

    # Reference byte order: current, manual, target_low(eco), target_high(comfort), offset, window_open, window_minutes
    return Temperatures(
        current=_temp(vals[0]),
        manual=_temp(vals[1]),
        eco=_temp(vals[2]),       # byte 2 = low setpoint = eco
        comfort=_temp(vals[3]),   # byte 3 = high setpoint = comfort
        offset=_temp(vals[4]),
        window_open=bool(vals[5]) if vals[5] != UNCHANGED else None,
        window_minutes=vals[6] if vals[6] != UNCHANGED else None,
    )


def encode_temperatures(
    comfort: Optional[float] = None,
    eco: Optional[float] = None,
    manual: Optional[float] = None,
    offset: float = 0.0,
    window_open: Optional[bool] = None,
    window_minutes: Optional[int] = None,
) -> bytes:
    """Encode temperature write payload.
    comfort/eco/manual=None → 0x80 (unchanged).
    offset is always written as a real value (never 0x80); caller must supply
    the current offset from cached status when not changing it.
    Both reference implementations (heizung.php, heaterControl.exp) always
    write 0x00 for the offset byte, never 0x80.
    Byte order (from reference): current, manual_mode, eco_low, comfort_high, offset, window_open, window_minutes
    """
    def _enc(v: Optional[float]) -> int:
        return -128 if v is None else int(v * 2)  # -128 = 0x80 = "do not change"

    return struct.pack(
        "7b",
        -128,                                               # byte 0: current (read-only)
        _enc(manual),                                       # byte 1: manual mode temp
        _enc(eco),                                          # byte 2: low setpoint (Absenken)
        _enc(comfort),                                      # byte 3: high setpoint (Heizen)
        int(offset * 2),                                    # byte 4: offset — always a real value
        (-128 if window_open is None else int(window_open)),
        (-128 if window_minutes is None else int(window_minutes)),
    )


def decode_datetime(data: bytes) -> datetime:
    """Decode 5-byte datetime: minute, hour, day, month, year-2000."""
    if len(data) < 5:
        raise ValueError(f"Expected 5 bytes, got {len(data)}")
    minute, hour, day, month, year_offset = struct.unpack("5B", data[:5])
    return datetime(2000 + year_offset, month, day, hour, minute)


def encode_datetime(dt: Optional[datetime] = None) -> bytes:
    """Encode datetime to 5 bytes. Uses current time if not provided."""
    dt = dt or datetime.now()
    return bytes([dt.minute, dt.hour, dt.day, dt.month, dt.year - 2000])


def _minutes_to_time(minutes_x10: int) -> Optional[time]:
    """Convert 10-minute increment value to time. 0xFF = disabled, 144 = 24:00 (end-of-day)."""
    if minutes_x10 == 0xFF or minutes_x10 >= 144:
        # 144 * 10 = 1440 min = 24:00 — Python time can't represent this; treat as end-of-day = None
        return None
    total_minutes = minutes_x10 * 10
    return time(total_minutes // 60, total_minutes % 60)


def _time_to_minutes(t: Optional[time]) -> int:
    """Convert time to 10-minute increment value. None → 0xFF."""
    if t is None:
        return 0xFF
    return (t.hour * 60 + t.minute) // 10


def decode_day_schedule(data: bytes) -> DaySchedule:
    """Decode 8-byte day schedule: 4 × (start, end) in 10-min increments."""
    if len(data) < 8:
        raise ValueError(f"Expected 8 bytes, got {len(data)}")
    periods = []
    for i in range(4):
        start = _minutes_to_time(data[i * 2])
        end = _minutes_to_time(data[i * 2 + 1])
        periods.append(TimePeriod(start=start, end=end))
    # Sort: active periods (with start time) first by start time, then disabled
    active = sorted([p for p in periods if p.start is not None], key=lambda p: p.start)
    inactive = [p for p in periods if p.start is None]
    return DaySchedule(periods=active + inactive)


def encode_day_schedule(schedule: DaySchedule) -> bytes:
    """Encode day schedule to 8 bytes."""
    result = []
    for i in range(4):
        if i < len(schedule.periods):
            p = schedule.periods[i]
            result.append(_time_to_minutes(p.start))
            result.append(_time_to_minutes(p.end))
        else:
            result.extend([0xFF, 0xFF])  # disabled
    return bytes(result)


def decode_holiday(data: bytes) -> Holiday:
    """Decode 9-byte holiday slot.
    Format (reference): hour_start, day_start, month_start, year_start,
                        hour_end, day_end, month_end, year_end, temp(signed ×2)
    """
    if len(data) < 9:
        raise ValueError(f"Expected 9 bytes, got {len(data)}")
    ho_start, da_start, mo_start, ye_start, \
        ho_end, da_end, mo_end, ye_end, temp = struct.unpack("<BBBBBBBBb", data)

    invalid = (
        ho_start > 23 or ho_end > 23
        or da_start < 1 or da_start > 31 or da_end < 1 or da_end > 31
        or mo_start < 1 or mo_start > 12 or mo_end < 1 or mo_end > 12
        or ye_start > 99 or ye_end > 99
        or temp == -128
    )
    if invalid:
        return Holiday(active=False)

    try:
        start = datetime(2000 + ye_start, mo_start, da_start, ho_start)
        end   = datetime(2000 + ye_end,   mo_end,   da_end,   ho_end)
    except ValueError:
        return Holiday(active=False)

    return Holiday(start=start, end=end, temperature=temp / 2.0, active=True)


def encode_holiday(start: datetime, end: datetime, temperature: float) -> bytes:
    """Encode holiday slot to 9 bytes (reference format)."""
    return struct.pack(
        "<BBBBBBBBb",
        start.hour, start.day, start.month, start.year - 2000,
        end.hour,   end.day,   end.month,   end.year - 2000,
        int(temperature * 2),
    )


def encode_holiday_clear() -> bytes:
    """Encode a cleared (disabled) holiday slot."""
    return struct.pack("<BBBBBBBBb", 128, 128, 128, 128, 128, 128, 128, 128, -128)


def get_day_uuid(day: int) -> str:
    """Get UUID for day schedule (1=Monday, 7=Sunday)."""
    if not 1 <= day <= 7:
        raise ValueError("Day must be 1 (Monday) to 7 (Sunday)")
    return _DAY_UUIDS[day - 1]


def get_holiday_uuid(slot: int) -> str:
    """Get UUID for holiday slot (1-8)."""
    if not 1 <= slot <= 8:
        raise ValueError("Slot must be 1–8")
    return _HOLIDAY_UUIDS[slot - 1]


@dataclass
class Flags:
    """Decoded FLAGS characteristic (3 bytes, UUID 47e9ee2a)."""
    child_lock: Optional[bool] = None      # Byte 0, bit 7 (0x80) — Kindersicherung
    manual_mode: Optional[bool] = None     # Byte 1, bit 1 — Manuell-Modus
    dst_active: Optional[bool] = None      # Byte 0, bit 0 — Sommerzeit aktiv
    antifrost: Optional[bool] = None       # Byte 0, bit 2 — Frostschutz
    raw: bytes = field(default_factory=bytes)


def decode_flags(data: bytes) -> Flags:
    """Decode 3-byte FLAGS characteristic.
    Byte 0: bit 7 = child_lock, bit 2 = antifrost, bit 0 = dst
    Byte 1: bit 1 = manual_mode
    Confirmed from device: 0x800008 = child_lock ON, 0x000008 = child_lock OFF
    """
    if len(data) < 3:
        return Flags(raw=bytes(data))
    b0, b1, _b2 = data[0], data[1], data[2]
    return Flags(
        child_lock=bool(b0 & 0x80),   # byte 0, bit 7 — confirmed empirically
        dst_active=bool(b0 & 0x01),
        antifrost=bool(b0 & 0x04),
        manual_mode=bool(b1 & 0x02),
        raw=bytes(data),
    )


DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def day_name_to_index(name: str) -> int:
    """Convert day name to index (1-7)."""
    try:
        return DAY_NAMES.index(name.lower()) + 1
    except ValueError:
        raise ValueError(f"Unknown day: {name!r}. Use: {DAY_NAMES}")
