"""Historical data routes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ... import database as db

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{address}")
async def get_history(
    address: str,
    hours: Optional[int] = Query(None, ge=1, le=8760, description="Last N hours (shortcut)"),
    from_dt: Optional[datetime] = Query(None, alias="from"),
    to_dt: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=5000),
):
    device = await db.get_device(address)
    if not device:
        raise HTTPException(404, "Device not found")

    if hours is not None:
        from_dt = datetime.utcnow() - timedelta(hours=hours)

    rows = await db.get_history(address, from_dt=from_dt, to_dt=to_dt, limit=limit)
    return {"address": address, "count": len(rows), "records": rows}


@router.get("")
async def get_all_history(
    hours: Optional[int] = Query(24, ge=1, le=8760),
    limit: int = Query(1000, ge=1, le=10000),
):
    """History for all configured devices — used by the monitor dashboard."""
    devices = await db.list_devices()
    from_dt = datetime.utcnow() - timedelta(hours=hours)
    result = []
    for dev in devices:
        rows = await db.get_history(dev["address"], from_dt=from_dt, limit=limit)
        result.append({
            "address": dev["address"],
            "name": dev["name"],
            "records": rows,
        })
    return result
