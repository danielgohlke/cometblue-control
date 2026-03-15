"""Global settings routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ... import database as db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AutoPollBody(BaseModel):
    enabled: bool


@router.patch("/auto_poll")
async def set_auto_poll(body: AutoPollBody):
    await db.set_setting("auto_poll", "true" if body.enabled else "false")
    return {"auto_poll": body.enabled}
