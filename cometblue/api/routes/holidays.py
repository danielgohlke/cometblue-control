"""Holiday slot routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import models
from ... import database as db
from ...device import CometBlueDevice
from ...protocol import Holiday

router = APIRouter(prefix="/api/devices", tags=["holidays"])


def _holiday_out(h: Holiday) -> dict:
    return {
        "slot": h.slot,
        "active": h.active,
        "start": h.start.isoformat() if h.start else None,
        "end": h.end.isoformat() if h.end else None,
        "temperature": h.temperature,
    }


@router.get("/{address}/holidays")
async def get_holidays(address: str):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            holidays = await dev.get_all_holidays()
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    return [_holiday_out(h) for h in holidays]


@router.put("/{address}/holidays/{slot}")
async def set_holiday(address: str, slot: int, body: models.HolidaySet):
    if not 1 <= slot <= 8:
        raise HTTPException(400, "Slot must be 1–8")

    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    holiday = Holiday(
        slot=slot,
        start=body.start,
        end=body.end,
        temperature=body.temperature,
        active=body.active,
    )

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            await dev.set_holiday(slot, holiday)
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    return {"status": "ok", "slot": slot}


@router.delete("/{address}/holidays/{slot}", status_code=204)
async def clear_holiday(address: str, slot: int):
    if not 1 <= slot <= 8:
        raise HTTPException(400, "Slot must be 1–8")

    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            await dev.clear_holiday(slot)
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")
