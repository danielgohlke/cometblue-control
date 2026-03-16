"""Device management routes."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import models
from ... import config, database as db
from ...device import CometBlueDevice
from ...discovery import find_by_mac
from ...scheduler import trigger_poll_now, is_poll_running, get_poll_state

# Keep strong references to background tasks so they are not garbage-collected
# before completion (asyncio only keeps weak refs to tasks by default).
_background_tasks: set = set()

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("", response_model=list[models.DeviceOut])
async def list_devices():
    devices = await db.list_devices()
    # Enrich with latest RSSI from device_status (set during poll) or scan_results
    scan = {r["address"]: r["rssi"] for r in await db.list_scan_results()}
    for dev in devices:
        status = await db.get_status(dev["address"])
        rssi = (status or {}).get("rssi") or scan.get(dev["address"].upper())
        dev["rssi"] = rssi
    return devices


@router.post("", response_model=models.DeviceOut, status_code=201)
async def add_device(body: models.DeviceAdd):
    existing = await db.get_device(body.address)
    if existing:
        raise HTTPException(409, f"Device {body.address} already exists")
    device = await db.add_device(
        address=body.address.upper(),
        name=body.name or body.address,
        pin=body.pin,
        adapter=body.adapter,
    )
    # Auto-fill MAC from scan results if available
    scan_results = await db.list_scan_results()
    for r in scan_results:
        if r["address"].upper() == body.address.upper() and r.get("mac_address"):
            await db.update_device(body.address, mac_address=r["mac_address"])
            device = await db.get_device(body.address)
            break
    return device


@router.get("/poll-all-status")
async def poll_all_status():
    """Return the current poll-all state (running / last completed)."""
    return get_poll_state()


@router.post("/poll-all", status_code=202)
async def poll_all_devices():
    """Trigger a background poll of all devices. Returns immediately."""
    if is_poll_running():
        return {"status": "already_running"}
    task = asyncio.create_task(trigger_poll_now())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "triggered"}


@router.get("/{address}", response_model=models.DeviceOut)
async def get_device(address: str):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    return device


@router.patch("/{address}", response_model=models.DeviceOut)
async def patch_device(address: str, body: DevicePatch):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    updates = body.model_dump(exclude_none=True)
    if updates:
        await db.update_device(address, **updates)
    return await db.get_device(address)


@router.delete("/{address}", status_code=204)
async def delete_device(address: str):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    await db.delete_device(address)


@router.post("/{address}/reset", status_code=200)
async def reset_device_data(address: str):
    """Clear cached status and full history. Device config (name, PIN, MAC) is kept."""
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    await db.reset_device_data(address)
    return {"status": "ok", "address": address}


@router.get("/{address}/status")
async def get_status(address: str):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    status = await db.get_status(address)
    return status or {"address": address, "polled_at": None}


class DevicePatch(BaseModel):
    name: Optional[str] = None
    pin: Optional[int] = None
    adapter: Optional[str] = None
    mac_address: Optional[str] = None


class PinTestBody(BaseModel):
    pin: Optional[int] = None


@router.post("/{address}/test-pin")
async def test_pin(address: str, body: PinTestBody):
    """
    Verify a PIN against the device via BLE.
    Uses the device's stored PIN if none is provided in the request body.
    Returns {"valid": true/false}.
    """
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    pin = body.pin if body.pin is not None else device.get("pin")
    if pin is None:
        raise HTTPException(400, "No PIN provided and no PIN stored for this device")

    try:
        async with CometBlueDevice(address, adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            valid = await dev.test_pin(pin)
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")

    return {"address": address, "pin": pin, "valid": valid}


@router.patch("/{address}/flags")
async def set_flags(address: str, body: models.FlagsSet):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    try:
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                   mac_address=device.get("mac_address")) as dev:
            if body.child_lock is not None:
                await dev.set_child_lock(body.child_lock)
    except Exception as e:
        raise HTTPException(502, f"BLE error: {e}")
    return {"status": "ok"}


class ChildLockAllBody(BaseModel):
    enabled: bool
    addresses: list[str] = ["all"]


@router.post("/set-child-lock")
async def set_child_lock_bulk(body: ChildLockAllBody):
    """Set child lock on multiple or all devices."""
    if "all" in body.addresses:
        all_devs = await db.list_devices()
        targets = all_devs
    else:
        targets = [d for d in await db.list_devices() if d["address"].upper() in [a.upper() for a in body.addresses]]

    results = {}
    for device in targets:
        address = device["address"]
        try:
            async with CometBlueDevice(address, pin=device.get("pin"), adapter=device.get("adapter"),
                                       mac_address=device.get("mac_address")) as dev:
                await dev.set_child_lock(body.enabled)
            results[address] = "ok"
        except Exception as e:
            results[address] = str(e)

    return {"status": "done", "enabled": body.enabled, "results": results}


class AssignAddressBody(BaseModel):
    new_address: str


@router.post("/{address}/assign-address")
async def assign_address(address: str, body: AssignAddressBody):
    """Manually replace the UUID/address of a device — e.g. after battery replacement on macOS."""
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    new_address = body.new_address.upper()
    if new_address == address.upper():
        return {"status": "ok", "new_address": new_address}
    if await db.get_device(new_address):
        raise HTTPException(409, f"Address {new_address} is already in use by another device")
    await db.update_device_address(address, new_address)
    return {"status": "ok", "old_address": address.upper(), "new_address": new_address}


@router.post("/{address}/rediscover")
async def rediscover_device(address: str):
    """Scan for this device by its stored MAC address and update the UUID if it changed.
    Useful after battery replacement on macOS where CoreBluetooth assigns new UUIDs.
    """
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    mac = device.get("mac_address")
    if not mac:
        raise HTTPException(400, "No MAC address stored for this device — run a discovery scan first to record the MAC")

    cfg = config.get()
    adapter = cfg.get("bluetooth", {}).get("adapter") or device.get("adapter")

    found = await find_by_mac(mac, adapter=adapter)
    if not found:
        raise HTTPException(404, f"Device with MAC {mac} not found in BLE scan")

    new_address = found.address.upper()
    old_address = address.upper()

    if new_address == old_address:
        return {"status": "unchanged", "address": old_address, "mac": mac}

    await db.update_device_address(old_address, new_address)
    return {"status": "updated", "old_address": old_address, "new_address": new_address, "mac": mac}


@router.post("/{address}/poll")
async def poll_device(address: str):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")
    started = await trigger_poll_now(address)
    if not started:
        raise HTTPException(409, "A poll is already in progress — please wait")
    status = await db.get_status(address)
    return status or {"address": address, "polled_at": None}
