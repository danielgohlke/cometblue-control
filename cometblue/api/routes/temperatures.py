"""Temperature read/write routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import models
from ... import database as db
from ...device import CometBlueDevice
from ...scheduler import trigger_poll_now

router = APIRouter(prefix="/api/devices", tags=["temperatures"])


@router.get("/{address}/temperatures")
async def get_temperatures(address: str):
    """Return latest cached temperatures (from last poll)."""
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    status = await db.get_status(address)
    if not status:
        raise HTTPException(503, "No data yet — trigger a poll first")
    return {
        "address": address,
        "temperatures": {
            k: status[f"temp_{k}"]
            for k in ("current", "manual", "comfort", "eco", "offset")
        },
        "window_open": status.get("window_open"),
        "window_minutes": status.get("window_minutes"),
        "polled_at": status.get("polled_at"),
    }


@router.put("/{address}/temperatures", status_code=200)
async def set_temperatures(address: str, body: models.TemperaturesSet):
    """Write temperature setpoints directly to the device via BLE."""
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    # Use cached offset if not explicitly provided, to avoid resetting a configured offset to 0
    offset = body.offset
    if offset is None:
        status = await db.get_status(address)
        offset = (status or {}).get("temp_offset") or 0.0

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            await dev.set_temperatures(
                comfort=body.comfort,
                eco=body.eco,
                offset=offset,
                window_open=body.window_open,
                window_minutes=body.window_minutes,
            )
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    # Update DB directly so the UI reflects the new values immediately,
    # without a second BLE connection (which is expensive on Pi 3B+).
    status = await db.get_status(address) or {}
    if body.comfort is not None:
        status["temp_comfort"] = body.comfort
    if body.eco is not None:
        status["temp_eco"] = body.eco
    if body.offset is not None:
        status["temp_offset"] = body.offset
    if status:
        await db.save_status(address, status)

    return {"status": "ok", "address": address}


@router.post("/{address}/sync-time", status_code=200)
async def sync_time(address: str):
    """Write the current system time to the device."""
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            await dev.sync_time()
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    return {"status": "ok", "address": address}
