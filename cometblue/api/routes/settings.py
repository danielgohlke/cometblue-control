"""Global settings routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import database as db
from ... import scheduler

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AutoPollBody(BaseModel):
    enabled: bool


class PollIntervalBody(BaseModel):
    poll_interval: int  # seconds


@router.patch("/auto_poll")
async def set_auto_poll(body: AutoPollBody):
    await db.set_setting("auto_poll", "true" if body.enabled else "false")
    return {"auto_poll": body.enabled}


@router.put("/poll-interval")
async def set_poll_interval(body: PollIntervalBody):
    """Update the background polling interval (seconds). Minimum 60s."""
    if body.poll_interval < 60:
        raise HTTPException(400, "poll_interval must be at least 60 seconds")
    await db.set_setting("poll_interval", str(body.poll_interval))
    scheduler.update_poll_interval(body.poll_interval)
    return {"poll_interval": body.poll_interval, "next_poll": scheduler.get_next_run()}
