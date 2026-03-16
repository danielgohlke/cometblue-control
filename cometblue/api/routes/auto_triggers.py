"""Auto-trigger routes — scheduled scenario/profile application."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import database as db
from ... import auto_trigger as at

router = APIRouter(prefix="/api/auto-triggers", tags=["auto-triggers"])


class TriggerBody(BaseModel):
    name: str
    type: str           # 'scenario' | 'profile'
    target_id: str      # preset id (str of int) or profile name
    days: list[str]     # ['daily'] or ['mon','tue',...]
    time_hm: str        # 'HH:MM'
    enabled: bool = True


def _with_next(trigger: dict) -> dict:
    return {**trigger, "next_run": at.get_next_run(trigger["id"])}


@router.get("")
async def list_triggers():
    return [_with_next(t) for t in await db.list_auto_triggers()]


@router.post("", status_code=201)
async def create_trigger(body: TriggerBody):
    t = await db.create_auto_trigger(
        body.name, body.type, body.target_id, body.days, body.time_hm, body.enabled
    )
    await at.refresh(t["id"])
    return _with_next(t)


@router.put("/{trigger_id}")
async def update_trigger(trigger_id: int, body: TriggerBody):
    if not await db.get_auto_trigger(trigger_id):
        raise HTTPException(404, "Trigger not found")
    await db.update_auto_trigger(
        trigger_id, body.name, body.type, body.target_id, body.days, body.time_hm, body.enabled
    )
    await at.refresh(trigger_id)
    return _with_next(await db.get_auto_trigger(trigger_id))


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(trigger_id: int):
    if not await db.get_auto_trigger(trigger_id):
        raise HTTPException(404, "Trigger not found")
    at.unschedule(trigger_id)
    await db.delete_auto_trigger(trigger_id)


@router.post("/{trigger_id}/run")
async def run_trigger_now(trigger_id: int):
    if not await db.get_auto_trigger(trigger_id):
        raise HTTPException(404, "Trigger not found")
    await at._run_trigger(trigger_id)
    return _with_next(await db.get_auto_trigger(trigger_id))
