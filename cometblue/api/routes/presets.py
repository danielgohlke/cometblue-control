"""Scene/preset routes — apply multiple profiles to specific devices at once."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ... import database as db
from ... import profiles as prof

router = APIRouter(prefix="/api/presets", tags=["presets"])


class PresetBody(BaseModel):
    name: str
    assignments: dict[str, str]  # address → profile name


@router.get("")
async def list_presets():
    return await db.list_presets()


@router.get("/{preset_id}")
async def get_preset(preset_id: int):
    preset = await db.get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    return preset


@router.post("", status_code=201)
async def create_preset(body: PresetBody):
    try:
        return await db.create_preset(body.name, body.assignments)
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(409, f"Preset '{body.name}' already exists")
        raise HTTPException(500, str(e))


@router.put("/{preset_id}")
async def update_preset(preset_id: int, body: PresetBody):
    preset = await db.get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    await db.update_preset(preset_id, body.name, body.assignments)
    return await db.get_preset(preset_id)


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(preset_id: int):
    preset = await db.get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    await db.delete_preset(preset_id)


@router.post("/{preset_id}/apply")
async def apply_preset(preset_id: int):
    preset = await db.get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")

    items = [(addr, pname) for addr, pname in preset["assignments"].items() if pname]
    total = len(items)

    async def stream():
        results = {}
        for i, (address, profile_name) in enumerate(items):
            yield {
                "event": "progress",
                "data": json.dumps({"address": address, "profile": profile_name, "index": i, "total": total}),
            }
            try:
                res = await prof.apply_profile(profile_name, [address], apply_schedules=True)
                status = res.get(address, "ok")
            except Exception as e:
                status = str(e)
            results[address] = status
            yield {
                "event": "result",
                "data": json.dumps({"address": address, "status": status}),
            }
        yield {
            "event": "done",
            "data": json.dumps({"preset": preset["name"], "results": results}),
        }

    return EventSourceResponse(stream())
