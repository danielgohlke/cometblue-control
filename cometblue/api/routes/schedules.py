"""Weekly schedule routes."""

from __future__ import annotations

from datetime import time

from fastapi import APIRouter, HTTPException

from .. import models
from ... import database as db
from ...device import CometBlueDevice
from ...protocol import DaySchedule, TimePeriod, DAY_NAMES, day_name_to_index

router = APIRouter(prefix="/api/devices", tags=["schedules"])


def _fmt_time(t) -> str | None:
    if t is None:
        return None
    return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)


def _parse_time(s: str | None):
    if not s:
        return None
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


@router.get("/{address}/schedules")
async def get_schedules(address: str):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            schedules = await dev.get_all_day_schedules()
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    result = []
    for day_name, sched in schedules.items():
        result.append({
            "day": day_name,
            "periods": [
                {"start": _fmt_time(p.start), "end": _fmt_time(p.end)}
                for p in sched.periods
            ],
        })
    return result


@router.put("/{address}/schedules")
async def set_full_schedule(address: str, body: dict):
    """
    Set weekly schedule. Body: { "monday": [{start, end}, ...], ... }
    Each day can have up to 4 periods.
    """
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            for day_name, periods_raw in body.items():
                if day_name.lower() not in DAY_NAMES:
                    continue
                day_idx = day_name_to_index(day_name)
                periods = []
                for p in (periods_raw or []):
                    periods.append(TimePeriod(
                        start=_parse_time(p.get("start")),
                        end=_parse_time(p.get("end")),
                    ))
                while len(periods) < 4:
                    periods.append(TimePeriod())
                await dev.set_day_schedule(day_idx, DaySchedule(periods=periods[:4]))
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    return {"status": "ok"}


@router.put("/{address}/schedules/{day}")
async def set_day_schedule(address: str, day: str, body: models.DayScheduleSet):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        day_idx = day_name_to_index(day)
    except ValueError as e:
        raise HTTPException(400, str(e))

    periods = []
    for p in body.periods:
        periods.append(TimePeriod(
            start=_parse_time(p.start),
            end=_parse_time(p.end),
        ))
    while len(periods) < 4:
        periods.append(TimePeriod())

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            await dev.set_day_schedule(day_idx, DaySchedule(periods=periods[:4]))
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    return {"status": "ok", "day": day}
