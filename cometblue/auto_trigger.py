"""Scheduled auto-apply of scenarios and profiles."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.triggers.cron import CronTrigger

from . import database as db
from . import profiles as prof

log = logging.getLogger(__name__)

# Set by init() — reference to the shared APScheduler instance from scheduler.py
_scheduler = None


def init(scheduler_instance) -> None:
    """Call once at startup with the running AsyncIOScheduler instance."""
    global _scheduler
    _scheduler = scheduler_instance


async def load_all() -> None:
    """Schedule all enabled triggers from DB — call once after init()."""
    triggers = await db.list_auto_triggers()
    for t in triggers:
        if t["enabled"]:
            _schedule(t)
    log.info("Loaded %d auto-trigger(s)", sum(1 for t in triggers if t["enabled"]))


def _days_to_cron(days: list[str]) -> str:
    """Convert days list to APScheduler day_of_week string."""
    if not days or "daily" in days:
        return "*"
    return ",".join(days)


def _schedule(trigger: dict) -> None:
    if not _scheduler:
        return
    job_id = f"auto_trigger_{trigger['id']}"
    hour, minute = trigger["time_hm"].split(":")
    _scheduler.add_job(
        _run_trigger,
        trigger=CronTrigger(
            day_of_week=_days_to_cron(trigger["days"]),
            hour=int(hour),
            minute=int(minute),
        ),
        args=[trigger["id"]],
        id=job_id,
        name=f"Auto: {trigger['name']}",
        replace_existing=True,
        misfire_grace_time=300,
    )
    log.info(
        "Scheduled auto-trigger '%s' at %s on %s",
        trigger["name"], trigger["time_hm"], trigger["days"],
    )


def unschedule(trigger_id: int) -> None:
    if not _scheduler:
        return
    job_id = f"auto_trigger_{trigger_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
        log.debug("Removed auto-trigger job %s", job_id)


async def refresh(trigger_id: int) -> None:
    """Re-sync scheduler after a create/update/delete."""
    unschedule(trigger_id)
    trigger = await db.get_auto_trigger(trigger_id)
    if trigger and trigger["enabled"]:
        _schedule(trigger)


def get_next_run(trigger_id: int) -> Optional[str]:
    if not _scheduler:
        return None
    job = _scheduler.get_job(f"auto_trigger_{trigger_id}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


async def _run_trigger(trigger_id: int) -> None:
    trigger = await db.get_auto_trigger(trigger_id)
    if not trigger or not trigger["enabled"]:
        return
    log.info(
        "Running auto-trigger '%s' (type=%s, target=%s)",
        trigger["name"], trigger["type"], trigger["target_id"],
    )
    try:
        if trigger["type"] == "scenario":
            preset = await db.get_preset(int(trigger["target_id"]))
            if not preset:
                log.warning("Auto-trigger '%s': scenario %s not found", trigger["name"], trigger["target_id"])
                return
            for address, profile_name in preset["assignments"].items():
                if profile_name:
                    await prof.apply_profile(profile_name, [address], apply_schedules=True)
        elif trigger["type"] == "profile":
            devices = await db.list_devices(active_only=True)
            addresses = [d["address"] for d in devices]
            if addresses:
                await prof.apply_profile(trigger["target_id"], addresses, apply_schedules=True)
    except Exception as e:
        log.error("Auto-trigger '%s' failed: %s", trigger["name"], e)
    finally:
        await db.touch_auto_trigger(trigger_id)
