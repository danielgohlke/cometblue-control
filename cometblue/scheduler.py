"""Background polling using APScheduler."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import database as db
from .device import poll_device

log = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_adapter: Optional[str] = None


def init(poll_interval: int = 300, adapter: Optional[str] = None):
    """Initialize the scheduler. Call once at startup."""
    global _scheduler, _adapter
    _adapter = adapter
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _poll_all_devices,
        trigger=IntervalTrigger(seconds=poll_interval),
        id="poll_all",
        name="Poll all CometBlue devices",
        replace_existing=True,
        misfire_grace_time=60,
    )
    _scheduler.start()
    log.info("Scheduler started, polling every %ds", poll_interval)


def shutdown():
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")


def get_next_run() -> Optional[str]:
    if not _scheduler:
        return None
    job = _scheduler.get_job("poll_all")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


async def trigger_poll_now(address: Optional[str] = None):
    """Immediately poll one or all devices."""
    if address:
        await _poll_single(address)
    else:
        await _poll_all_devices()


async def _poll_all_devices():
    if await db.get_setting("auto_poll", "true") != "true":
        log.debug("Auto-poll disabled, skipping scheduled poll")
        return
    devices = await db.list_devices(active_only=True)
    if not devices:
        log.debug("No devices configured, skipping poll")
        return
    log.info("Polling %d device(s)...", len(devices))
    tasks = [_poll_single(d["address"]) for d in devices]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _poll_single(address: str):
    device = await db.get_device(address)
    if not device:
        return
    pin = device.get("pin")
    mac_address = device.get("mac_address")
    log.debug("Polling %s...", address)
    result = await poll_device(address, pin=pin, adapter=_adapter, mac_address=mac_address)

    # Handle auto-resolved address (UUID changed after battery replacement)
    new_address = result.get("new_address")
    if new_address:
        log.info("Auto-resolved address for device: %s → %s", address, new_address)
        await db.update_device_address(address, new_address)
        effective_address = new_address
    else:
        effective_address = address

    await db.save_status(effective_address, result)
    await db.update_device_seen(effective_address)
    log.debug("Poll complete for %s: %s", effective_address, result.get("error") or "ok")
