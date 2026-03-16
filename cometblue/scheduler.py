"""Background polling using APScheduler."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

IS_MACOS = sys.platform == "darwin"

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import database as db
from .device import poll_device

log = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_adapter: Optional[str] = None

# Poll state — used by the UI to wait for background poll completion
_poll_running: bool = False
_poll_started_at: Optional[datetime] = None
_poll_completed_at: Optional[datetime] = None


def get_poll_state() -> dict:
    return {
        "running": _poll_running,
        "started_at": _poll_started_at.isoformat() if _poll_started_at else None,
        "completed_at": _poll_completed_at.isoformat() if _poll_completed_at else None,
    }


def is_poll_running() -> bool:
    return _poll_running


def init(poll_interval: int = 300, adapter: Optional[str] = None):
    """Initialize the scheduler. Call once at startup."""
    global _scheduler, _adapter
    _adapter = adapter
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _scheduled_poll,
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
    """Immediately poll one or all devices (always runs, ignores auto_poll setting)."""
    if address:
        await _poll_single(address)
    else:
        await _poll_all_devices(manual=True)


async def _scheduled_poll():
    """Called by the scheduler — respects the auto_poll setting."""
    if await db.get_setting("auto_poll", "true") != "true":
        log.debug("Auto-poll disabled, skipping scheduled poll")
        return
    await _poll_all_devices(manual=False)


async def _poll_all_devices(manual: bool = False):
    global _poll_running, _poll_started_at, _poll_completed_at
    if _poll_running:
        log.debug("Poll already running, skipping")
        return
    devices = await db.list_devices(active_only=True)
    if not devices:
        log.debug("No devices configured, skipping poll")
        return

    _poll_running = True
    _poll_started_at = datetime.now(timezone.utc)
    log.info("Polling %d device(s) [platform=%s]...", len(devices), sys.platform)

    try:
        if IS_MACOS:
            await _poll_all_macos(devices)
        else:
            await _poll_all_linux(devices)
    finally:
        _poll_running = False
        _poll_completed_at = datetime.now(timezone.utc)
        log.info("Poll cycle complete")


async def _poll_all_macos(devices: list):
    """macOS: CoreBluetooth handles concurrent connections — poll all in parallel.

    The _ble_lock semaphore in device.py still serialises the actual GATT
    operations (CometBlue only accepts one connection at a time), but asyncio
    scheduling is more responsive and errors surface faster than sequential.
    Per-device timeout is shorter because CoreBluetooth service discovery is fast.
    """
    per_device_timeout = 30  # connect(15s) + reads
    async def _safe_poll(address: str):
        try:
            await asyncio.wait_for(_poll_single(address), timeout=per_device_timeout)
        except asyncio.TimeoutError:
            log.error("Poll timed out (>%ds) for %s — skipping", per_device_timeout, address)
        except Exception as e:
            log.error("Unexpected error polling %s: %s", address, e)

    await asyncio.gather(*[_safe_poll(d["address"]) for d in devices])


async def _poll_all_linux(devices: list):
    """Linux / Raspberry Pi: BlueZ only supports one BLE operation at a time.

    Poll strictly sequentially with a generous per-device timeout to prevent
    one stuck device from blocking the rest.
    Pi 3B+ needs ~45s connect + ~30s GATT service discovery on first connect.
    """
    per_device_timeout = 120  # connect(45s) + reads + EOFError reset(10s)
    for device in devices:
        try:
            await asyncio.wait_for(_poll_single(device["address"]), timeout=per_device_timeout)
        except asyncio.TimeoutError:
            log.error("Poll timed out (>%ds) for %s — skipping", per_device_timeout, device["address"])
        except Exception as e:
            log.error("Unexpected error polling %s: %s", device["address"], e)


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
