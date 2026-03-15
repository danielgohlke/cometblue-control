"""Profile routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .. import models
from ... import database as db
from ... import profiles as prof

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("")
async def list_profiles():
    return [{"name": n} for n in prof.list_profiles()]


@router.get("/{name}", response_model=models.ProfileOut)
async def get_profile(name: str):
    try:
        data = prof.load_profile(name)
    except FileNotFoundError:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"name": name, **data}


@router.put("/{name}", status_code=200)
async def update_profile(name: str, body: dict):
    prof.save_profile(name, body)
    return {"status": "ok", "name": name}


@router.delete("/{name}", status_code=200)
async def delete_profile(name: str):
    try:
        prof.delete_profile(name)
    except FileNotFoundError:
        raise HTTPException(404, f"Profile '{name}' not found")
    return {"status": "deleted", "name": name}


@router.post("/{name}/apply")
async def apply_profile(name: str, body: models.ProfileApply):
    try:
        prof.load_profile(name)  # Validate profile exists
    except FileNotFoundError:
        raise HTTPException(404, f"Profile '{name}' not found")

    # Resolve device list
    if "all" in body.devices:
        all_devs = await db.list_devices()
        addresses = [d["address"] for d in all_devs]
    else:
        addresses = [a.upper() for a in body.devices]

    if not addresses:
        return {"status": "no_devices", "results": {}}

    total = len(addresses)

    async def stream():
        from ...device import CometBlueDevice
        profile_data = prof.load_profile(name)
        results = {}
        for i, address in enumerate(addresses):
            yield {
                "event": "progress",
                "data": json.dumps({"address": address, "index": i, "total": total}),
            }
            device_cfg = await db.get_device(address)
            try:
                status = await db.get_status(address)
                cached_offset = (status or {}).get("temp_offset") or 0.0
                pin = device_cfg.get("pin") if device_cfg else None
                mac_address = device_cfg.get("mac_address") if device_cfg else None
                async with CometBlueDevice(address, pin=pin, mac_address=mac_address) as dev:
                    await dev.set_temperatures(
                        comfort=profile_data.get("comfort_temp"),
                        eco=profile_data.get("eco_temp"),
                        offset=cached_offset,
                    )
                    child_lock = profile_data.get("child_lock")
                    if child_lock is not None:
                        await dev.set_child_lock(bool(child_lock))
                    if body.apply_schedules and "schedules" in profile_data:
                        schedules = prof.profile_to_schedules(profile_data)
                        from ...protocol import DAY_NAMES
                        for idx, day_name in enumerate(DAY_NAMES, start=1):
                            if day_name in schedules:
                                await dev.set_day_schedule(idx, schedules[day_name])
                # Update DB cache so dashboard reflects new values immediately
                cached = await db.get_status(address) or {}
                if profile_data.get("comfort_temp") is not None:
                    cached["temp_comfort"] = profile_data["comfort_temp"]
                if profile_data.get("eco_temp") is not None:
                    cached["temp_eco"] = profile_data["eco_temp"]
                if cached:
                    await db.save_status(address, cached)
                result_status = "ok"
            except Exception as e:
                result_status = str(e)
            results[address] = result_status
            yield {
                "event": "result",
                "data": json.dumps({"address": address, "status": result_status}),
            }
        yield {
            "event": "done",
            "data": json.dumps({"profile": name, "results": results}),
        }

    return EventSourceResponse(stream())
