"""BLE discovery routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from .. import models
from ... import discovery, config, database as db

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.get("/known")
async def get_known():
    """Return all devices that were ever found via BLE scan (persisted across restarts)."""
    results = await db.list_scan_results()
    # Annotate with whether they're already configured
    devices = await db.list_devices(active_only=False)
    configured = {d["address"] for d in devices}
    for r in results:
        r["configured"] = r["address"] in configured
    return results


@router.post("/scan", response_model=list[models.DiscoverResult])
async def scan(
    timeout: float = Query(default=10.0, ge=3.0, le=60.0),
):
    """Full blocking scan — returns all results at once after timeout."""
    cfg = config.get()
    adapter = cfg.get("bluetooth", {}).get("adapter")
    found = await discovery.scan(timeout=timeout, adapter=adapter)
    all_devices = await db.list_devices(active_only=False)
    mac_to_device = {dev["mac_address"].upper(): dev for dev in all_devices if dev.get("mac_address")}

    for d in found:
        await db.upsert_scan_result(d.address, d.name, d.rssi, d.mac_address)
        if d.mac_address:
            mac_up = d.mac_address.upper()
            existing_by_address = await db.get_device(d.address)
            if existing_by_address:
                # Same UUID — just fill in MAC if missing
                if not existing_by_address.get("mac_address"):
                    await db.update_device(d.address, mac_address=d.mac_address)
            elif mac_up in mac_to_device:
                # MAC matches a stored device with a different UUID → update UUID
                old_device = mac_to_device[mac_up]
                await db.update_device_address(old_device["address"], d.address)
                await db.update_device(d.address, mac_address=d.mac_address)

    return [
        {"address": d.address, "name": d.name, "rssi": d.rssi, "verified": d.verified}
        for d in found
    ]


@router.get("/stream")
async def stream_scan(
    timeout: float = Query(default=10.0, ge=3.0, le=60.0),
):
    """
    SSE stream — emits events as devices are found in real time.
    Also persists each found device to the database.

    Event types:
    - `device`   — {"address", "name", "rssi"}
    - `progress` — {"elapsed", "total"}
    - `done`     — {"found": N}
    """
    cfg = config.get()
    adapter = cfg.get("bluetooth", {}).get("adapter")

    async def generator():
        found_count = 0
        async for event_type, data in discovery.scan_streaming(timeout=timeout, adapter=adapter):
            if event_type == "device":
                found_count += 1
                await db.upsert_scan_result(data.address, data.name, data.rssi)
                yield {
                    "event": "device",
                    "data": json.dumps({
                        "address": data.address,
                        "name": data.name,
                        "rssi": data.rssi,
                    }),
                }
            elif event_type == "mac":
                # Post-scan: MAC discovered via System ID — persist it
                await db.upsert_scan_result(data.address, data.name or "", mac_address=data.mac_address)
                existing = await db.get_device(data.address)
                if existing and not existing.get("mac_address"):
                    await db.update_device(data.address, mac_address=data.mac_address)
            elif event_type == "progress":
                yield {
                    "event": "progress",
                    "data": json.dumps({"elapsed": round(data, 1), "total": timeout}),
                }
            elif event_type == "done":
                yield {
                    "event": "done",
                    "data": json.dumps({"found": found_count}),
                }

    return EventSourceResponse(generator())
