"""SQLite persistence — devices, history, cached status."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

log = logging.getLogger(__name__)

_DB_PATH: Path = Path.home() / ".cometblue" / "cometblue.db"


def set_db_path(path: Path):
    global _DB_PATH
    _DB_PATH = path


def get_db_path() -> Path:
    return _DB_PATH


async def init_db(path: Optional[Path] = None):
    """Create tables if they don't exist."""
    db_path = path or _DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                address     TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                pin         INTEGER,
                adapter     TEXT,
                mac_address TEXT,
                active      INTEGER NOT NULL DEFAULT 1,
                added_at    TEXT NOT NULL,
                last_seen   TEXT,
                metadata    TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS device_status (
                address         TEXT PRIMARY KEY,
                temp_current    REAL,
                temp_manual     REAL,
                temp_comfort    REAL,
                temp_eco        REAL,
                temp_offset     REAL,
                window_open     INTEGER,
                window_minutes  INTEGER,
                battery         INTEGER,
                rssi            INTEGER,
                child_lock      INTEGER,
                flags_raw       TEXT,
                device_time     TEXT,
                error           TEXT,
                polled_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                address         TEXT NOT NULL,
                temp_current    REAL,
                temp_manual     REAL,
                temp_comfort    REAL,
                temp_eco        REAL,
                battery         INTEGER,
                recorded_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_history_address_time
                ON history (address, recorded_at);

            CREATE TABLE IF NOT EXISTS scan_results (
                address     TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                rssi        INTEGER,
                mac_address TEXT,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_poll', 'false');

            CREATE TABLE IF NOT EXISTS presets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                assignments TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS auto_triggers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                type        TEXT NOT NULL,
                target_id   TEXT NOT NULL,
                days        TEXT NOT NULL DEFAULT '["daily"]',
                time_hm     TEXT NOT NULL DEFAULT '07:00',
                enabled     INTEGER NOT NULL DEFAULT 1,
                last_run    TEXT,
                created_at  TEXT NOT NULL
            );
        """)
        await db.commit()
    log.info("Database ready at %s", db_path)


async def _db():
    return aiosqlite.connect(_DB_PATH)


# ── Devices ───────────────────────────────────────────────────────────────────

async def add_device(address: str, name: str, pin: Optional[int] = None,
                     adapter: Optional[str] = None) -> dict:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO devices (address, name, pin, adapter, active, added_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (address.upper(), name, pin, adapter, now),
        )
        await db.commit()
    return await get_device(address)


async def get_device(address: str) -> Optional[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM devices WHERE address = ?", (address.upper(),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_devices(active_only: bool = True) -> list[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM devices"
        if active_only:
            query += " WHERE active = 1"
        async with db.execute(query + " ORDER BY name") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def update_device_address(old_address: str, new_address: str):
    """Replace the primary key (UUID/address) of a device — used after UUID change on macOS."""
    old = old_address.upper()
    new = new_address.upper()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("UPDATE devices SET address = ? WHERE address = ?", (new, old))
        await db.execute("UPDATE device_status SET address = ? WHERE address = ?", (new, old))
        await db.execute("UPDATE history SET address = ? WHERE address = ?", (new, old))
        await db.commit()
    log.info("Device address updated: %s → %s", old, new)


async def delete_device(address: str):
    """Remove device config only. History and status are kept so data survives re-add."""
    addr = address.upper()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("DELETE FROM devices WHERE address = ?", (addr,))
        await db.commit()


async def reset_device_data(address: str):
    """Clear cached status and full history for a device (config stays intact)."""
    addr = address.upper()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("DELETE FROM device_status WHERE address = ?", (addr,))
        await db.execute("DELETE FROM history WHERE address = ?", (addr,))
        await db.commit()


async def update_device(address: str, **fields):
    """Update arbitrary device fields (name, pin, adapter, mac_address)."""
    allowed = {"name", "pin", "adapter", "mac_address"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            f"UPDATE devices SET {set_clause} WHERE address = ?",
            (*updates.values(), address.upper()),
        )
        await db.commit()


async def update_device_seen(address: str):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE devices SET last_seen = ? WHERE address = ?",
            (datetime.utcnow().isoformat(), address.upper()),
        )
        await db.commit()


# ── Scan results (persisted discovery) ───────────────────────────────────────

async def upsert_scan_result(address: str, name: str, rssi: Optional[int] = None,
                             mac_address: Optional[str] = None):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE scan_results ADD COLUMN mac_address TEXT")
            await db.commit()
        except Exception:
            pass
        await db.execute("""
            INSERT INTO scan_results (address, name, rssi, mac_address, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                name = excluded.name,
                rssi = excluded.rssi,
                mac_address = COALESCE(excluded.mac_address, scan_results.mac_address),
                last_seen = excluded.last_seen
        """, (address.upper(), name, rssi, mac_address, now, now))
        await db.commit()


async def list_scan_results() -> list[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scan_results ORDER BY last_seen DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Status cache ──────────────────────────────────────────────────────────────

async def save_status(address: str, poll_result: dict):
    temps = poll_result.get("temperatures") or {}
    now = datetime.utcnow().isoformat()
    addr = address.upper()
    error = poll_result.get("error")

    rssi = poll_result.get("rssi")
    flags = poll_result.get("flags") or {}
    child_lock = flags.get("child_lock")
    flags_raw = flags.get("raw")

    async with aiosqlite.connect(_DB_PATH) as db:
        # Migrations — add columns that didn't exist in older schema versions
        for col_sql in [
            "ALTER TABLE device_status ADD COLUMN rssi INTEGER",
            "ALTER TABLE device_status ADD COLUMN child_lock INTEGER",
            "ALTER TABLE device_status ADD COLUMN flags_raw TEXT",
            "ALTER TABLE devices ADD COLUMN mac_address TEXT",
        ]:
            try:
                await db.execute(col_sql)
                await db.commit()
            except Exception:
                pass

        if error and not temps:
            # Poll failed — preserve existing temperature data, only update error + timestamp
            await db.execute("""
                INSERT INTO device_status (address, error, polled_at)
                VALUES (?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    error = excluded.error,
                    polled_at = excluded.polled_at
            """, (addr, error, now))
        else:
            # Successful poll — write all fields
            await db.execute("""
                INSERT OR REPLACE INTO device_status
                (address, temp_current, temp_manual, temp_comfort, temp_eco,
                 temp_offset, window_open, window_minutes, battery, rssi,
                 child_lock, flags_raw, device_time, error, polled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                addr,
                temps.get("current"), temps.get("manual"),
                temps.get("comfort"), temps.get("eco"),
                temps.get("offset"), temps.get("window_open"),
                temps.get("window_minutes"),
                poll_result.get("battery"),
                rssi,
                int(child_lock) if child_lock is not None else None,
                flags_raw,
                poll_result.get("device_time"),
                error, now,
            ))
        await db.commit()

    # Save MAC address to devices table if poll returned one
    mac_address = poll_result.get("mac_address")
    if mac_address:
        async with aiosqlite.connect(_DB_PATH) as db:
            await db.execute(
                "UPDATE devices SET mac_address = ? WHERE address = ?",
                (mac_address, addr),
            )
            await db.commit()

    # Only record history on success
    if not error and temps.get("current") is not None:
        await _append_history(addr, temps, poll_result.get("battery"))


async def _append_history(address: str, temps: dict, battery: Optional[int]):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("""
            INSERT INTO history
            (address, temp_current, temp_manual, temp_comfort, temp_eco, battery, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            address,
            temps.get("current"), temps.get("manual"),
            temps.get("comfort"), temps.get("eco"),
            battery,
            datetime.utcnow().isoformat(),
        ))
        await db.commit()


async def get_status(address: str) -> Optional[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM device_status WHERE address = ?", (address.upper(),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Presets (scenes) ──────────────────────────────────────────────────────────

async def list_presets() -> list[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM presets ORDER BY name") as cur:
            rows = await cur.fetchall()
            return [{"id": r["id"], "name": r["name"], "assignments": json.loads(r["assignments"])} for r in rows]


async def get_preset(preset_id: int) -> Optional[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {"id": row["id"], "name": row["name"], "assignments": json.loads(row["assignments"])}


async def create_preset(name: str, assignments: dict) -> dict:
    async with aiosqlite.connect(_DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO presets (name, assignments) VALUES (?, ?)",
            (name, json.dumps(assignments)),
        )
        await db.commit()
        return await get_preset(cur.lastrowid)


async def update_preset(preset_id: int, name: str, assignments: dict):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE presets SET name = ?, assignments = ? WHERE id = ?",
            (name, json.dumps(assignments), preset_id),
        )
        await db.commit()


async def delete_preset(preset_id: int):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(_DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


# ── Auto-triggers (scheduled scenario/profile application) ────────────────────

def _parse_trigger(row) -> dict:
    d = dict(row)
    d["days"] = json.loads(d["days"])
    d["enabled"] = bool(d["enabled"])
    return d


async def list_auto_triggers() -> list[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM auto_triggers ORDER BY time_hm, name") as cur:
            rows = await cur.fetchall()
            return [_parse_trigger(r) for r in rows]


async def get_auto_trigger(trigger_id: int) -> Optional[dict]:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM auto_triggers WHERE id = ?", (trigger_id,)) as cur:
            row = await cur.fetchone()
            return _parse_trigger(row) if row else None


async def create_auto_trigger(name: str, type: str, target_id: str,
                              days: list, time_hm: str, enabled: bool = True) -> dict:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(_DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO auto_triggers (name, type, target_id, days, time_hm, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, type, target_id, json.dumps(days), time_hm, int(enabled), now),
        )
        await db.commit()
        return await get_auto_trigger(cur.lastrowid)


async def update_auto_trigger(trigger_id: int, name: str, type: str, target_id: str,
                              days: list, time_hm: str, enabled: bool):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE auto_triggers SET name=?, type=?, target_id=?, days=?, time_hm=?, enabled=? WHERE id=?",
            (name, type, target_id, json.dumps(days), time_hm, int(enabled), trigger_id),
        )
        await db.commit()


async def delete_auto_trigger(trigger_id: int):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("DELETE FROM auto_triggers WHERE id = ?", (trigger_id,))
        await db.commit()


async def touch_auto_trigger(trigger_id: int):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE auto_triggers SET last_run = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), trigger_id),
        )
        await db.commit()


async def get_history(
    address: str,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    limit: int = 500,
) -> list[dict]:
    clauses = ["address = ?"]
    params: list = [address.upper()]

    if from_dt:
        clauses.append("recorded_at >= ?")
        params.append(from_dt.isoformat())
    if to_dt:
        clauses.append("recorded_at <= ?")
        params.append(to_dt.isoformat())

    params.append(limit)
    query = (
        "SELECT * FROM history WHERE " + " AND ".join(clauses)
        + " ORDER BY recorded_at DESC LIMIT ?"
    )

    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in reversed(rows)]
