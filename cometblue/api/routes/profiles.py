"""Profile routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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

    results = await prof.apply_profile(name, addresses, apply_schedules=body.apply_schedules)
    return {"status": "done", "profile": name, "results": results}
