# REST API Reference

**Base URL:** `http://localhost:8080` (configurable in `~/.cometblue/config.yaml`)

Interactive API docs (Swagger UI): **`http://localhost:8080/docs`**
OpenAPI schema: **`http://localhost:8080/openapi.json`**

---

## Table of Contents

- [Devices](#devices)
- [Temperatures](#temperatures)
- [Schedules](#schedules)
- [Holidays](#holidays)
- [Profiles](#profiles)
- [Scenarios (Presets)](#scenarios-presets)
- [Scheduler (Zeitplan)](#scheduler-zeitplan)
- [Discovery](#discovery)
- [History](#history)
- [Settings](#settings)
- [System](#system)

---

## Devices

### `GET /api/devices`
List all configured devices including last known RSSI and status.

**Response:**
```json
[
  {
    "address": "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX",
    "name": "Wohnzimmer",
    "pin": 0,
    "adapter": null,
    "mac_address": "XX:XX:XX:XX:XX:XX",
    "active": true,
    "added_at": "2026-03-10T12:00:00",
    "last_seen": "2026-03-16T08:00:00",
    "rssi": -71
  }
]
```

### `POST /api/devices`
Add a device. If the address is already known from a scan, the MAC address is filled in automatically.

**Body:**
```json
{ "address": "XXXXXXXX-...", "name": "Wohnzimmer", "pin": 0, "adapter": null }
```
**Response:** `201 Created` — device object

### `GET /api/devices/{address}`
Get a single device. **Response:** device object

### `PATCH /api/devices/{address}`
Update device name, PIN, adapter or MAC address (all fields optional).

**Body:** `{ "name": "Küche", "pin": 31337, "adapter": null, "mac_address": "XX:XX:XX:XX:XX:XX" }`

### `DELETE /api/devices/{address}`
Remove device. History records are kept. **Response:** `204 No Content`

### `GET /api/devices/{address}/status`
Last cached poll status — instant, no BLE required.

**Response:**
```json
{
  "address": "XXXXXXXX-...",
  "temp_current": 20.5,
  "temp_manual": null,
  "temp_comfort": 19.0,
  "temp_eco": 18.0,
  "temp_offset": 0.0,
  "window_open": 0,
  "window_minutes": null,
  "battery": 78,
  "rssi": -71,
  "child_lock": 0,
  "flags_raw": "000000",
  "device_time": "2026-03-16T08:00:00",
  "error": null,
  "polled_at": "2026-03-16T08:05:00"
}
```

### `GET /api/devices/{address}/info`
Cached device metadata (no BLE). Useful for displaying battery and last seen.

**Response:**
```json
{
  "address": "XXXXXXXX-...",
  "name": "Wohnzimmer",
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "adapter": null,
  "added_at": "2026-03-10T12:00:00",
  "last_seen": "2026-03-16T08:00:00",
  "battery": 78,
  "device_time": "2026-03-16T08:00:00",
  "polled_at": "2026-03-16T08:05:00",
  "error": null
}
```

### `POST /api/devices/{address}/poll`
Trigger an immediate BLE poll for this device.

**Response:** fresh status object (same as `/status`)
**409** if a poll is already running.

### `POST /api/devices/poll-all`
Trigger an immediate BLE poll of all configured devices (runs in background).

**Response:** `202 Accepted` — `{ "started": true }`

### `GET /api/devices/poll-all-status`
Check if a background poll is in progress.

**Response:**
```json
{
  "running": true,
  "current_device": "XXXXXXXX-...",
  "started_at": "2026-03-16T08:10:00Z",
  "completed_at": null
}
```

### `POST /api/devices/{address}/test-pin`
Test a PIN via BLE without saving it.

**Body:** `{ "pin": 31337 }` — omit to use the device's stored PIN
**Response:** `{ "address": "...", "pin": 31337, "valid": true }`

### `PATCH /api/devices/{address}/flags`
Set device flags (currently: child lock).

**Body:** `{ "child_lock": true }`
**Response:** `{ "status": "ok" }`

### `POST /api/devices/set-child-lock`
Bulk set child lock on all or specific devices.

**Body:**
```json
{ "enabled": true, "addresses": ["all"] }
// or specific devices:
{ "enabled": false, "addresses": ["XXXXXXXX-...", "YYYYYYYY-..."] }
```

### `POST /api/devices/{address}/rediscover`
Re-scan for a device by its stored MAC address. Needed on macOS after battery replacement when CoreBluetooth assigns a new UUID.

**Response:**
```json
{ "status": "updated", "old_address": "XXXXXXXX-...", "new_address": "YYYYYYYY-...", "mac": "XX:XX:XX:XX:XX:XX" }
// or if UUID unchanged:
{ "status": "unchanged", "address": "XXXXXXXX-...", "mac": "XX:XX:XX:XX:XX:XX" }
```

---

## Temperatures

### `GET /api/devices/{address}/temperatures`
Cached temperature setpoints from the last poll (no BLE).

**Response:**
```json
{
  "address": "XXXXXXXX-...",
  "temperatures": {
    "current": 20.5,
    "manual": null,
    "comfort": 19.0,
    "eco": 18.0,
    "offset": 0.0
  },
  "window_open": false,
  "window_minutes": null,
  "polled_at": "2026-03-16T08:05:00"
}
```

### `PUT /api/devices/{address}/temperatures`
Set temperature setpoints via BLE. Triggers an automatic poll afterwards.

**Body** (all fields optional):
```json
{ "comfort": 22.0, "eco": 17.0, "offset": 0.0 }
```

| Field | Range | Description |
|-------|-------|-------------|
| `comfort` | 5.0–35.0 °C | Heating temperature (during schedule) |
| `eco` | 5.0–35.0 °C | Setback temperature (outside schedule) |
| `offset` | -3.5–+3.5 °C | Calibration offset. Cached value is used if omitted. |

### `POST /api/devices/{address}/sync-time`
Write the current system time to the device.

**Response:** `{ "status": "ok", "address": "..." }`

---

## Schedules

Up to 4 heating periods per day, in 10-minute steps.

### `GET /api/devices/{address}/schedules`
Read the full weekly schedule via BLE.

**Response:**
```json
[
  {
    "day": "monday",
    "periods": [
      { "start": "07:00", "end": "12:00" },
      { "start": "12:10", "end": "19:00" },
      { "start": null, "end": null },
      { "start": null, "end": null }
    ]
  },
  { "day": "tuesday", "periods": [ ... ] }
]
```

### `PUT /api/devices/{address}/schedules`
Write the full weekly schedule. Only specified days are updated.

**Body:**
```json
{
  "monday":    [{ "start": "07:00", "end": "12:00" }, { "start": "12:10", "end": "19:00" }],
  "tuesday":   [{ "start": "07:00", "end": "19:00" }],
  "saturday":  [{ "start": "08:00", "end": "22:00" }]
}
```

### `PUT /api/devices/{address}/schedules/{day}`
Set schedule for a single day. `day` = `monday`–`sunday`.

**Body:** `{ "periods": [{ "start": "07:00", "end": "19:00" }] }` — max 4 periods

```bash
curl -X PUT http://localhost:8080/api/devices/XXXXXXXX-.../schedules/monday \
  -H "Content-Type: application/json" \
  -d '{"periods": [{"start": "07:00", "end": "12:00"}, {"start": "12:10", "end": "19:00"}]}'
```

---

## Holidays

8 holiday slots per device (slot 1–8).

### `GET /api/devices/{address}/holidays`
Read all holiday slots via BLE.

**Response:**
```json
[
  { "slot": 1, "active": true, "start": "2026-12-24T00:00:00", "end": "2027-01-02T23:59:00", "temperature": 15.0 },
  { "slot": 2, "active": false, "start": null, "end": null, "temperature": null }
]
```

### `PUT /api/devices/{address}/holidays/{slot}`
Set a holiday slot (slot 1–8).

**Body:**
```json
{
  "start": "2026-12-24T00:00:00",
  "end":   "2027-01-02T23:59:00",
  "temperature": 15.0,
  "active": true
}
```

```bash
curl -X PUT http://localhost:8080/api/devices/XXXXXXXX-.../holidays/1 \
  -H "Content-Type: application/json" \
  -d '{"start": "2026-12-24T00:00:00", "end": "2027-01-02T23:59:00", "temperature": 15.0, "active": true}'
```

### `DELETE /api/devices/{address}/holidays/{slot}`
Clear (deactivate) a holiday slot. **Response:** `204 No Content`

---

## Profiles

Profiles are stored as YAML in `~/.cometblue/profiles/`. Default profiles: `winter`, `summer`, `spring`, `holiday`, `weekday`, `weekend`, `aus`.

### `GET /api/profiles`
List all available profiles. **Response:** `[{ "name": "winter" }, ...]`

### `GET /api/profiles/{name}`
Get profile details including schedules and optional child lock.

**Response:**
```json
{
  "name": "winter",
  "comfort_temp": 22.0,
  "eco_temp": 17.0,
  "child_lock": null,
  "schedules": {
    "monday":   [{ "start": "07:00", "end": "12:00" }, { "start": "12:10", "end": "19:00" }],
    "saturday": [{ "start": "08:00", "end": "22:00" }]
  }
}
```

### `PUT /api/profiles/{name}`
Create or overwrite a profile.

**Body:**
```json
{
  "name": "winter",
  "comfort_temp": 22.0,
  "eco_temp": 17.0,
  "child_lock": null,
  "schedules": { "monday": [{ "start": "07:00", "end": "19:00" }] }
}
```

### `DELETE /api/profiles/{name}`
Delete a profile. **Response:** `{ "status": "deleted", "name": "winter" }`

### `POST /api/profiles/{name}/apply`
Apply a profile to devices via BLE (temperatures + optional schedules).

**Body:**
```json
{ "devices": ["all"], "apply_schedules": true }
```

**Response:**
```json
{ "status": "done", "profile": "winter", "results": { "XXXXXXXX-...": "ok" } }
```

```bash
# Apply to all devices including schedules:
curl -X POST http://localhost:8080/api/profiles/winter/apply \
  -H "Content-Type: application/json" \
  -d '{"devices": ["all"], "apply_schedules": true}'

# Temperatures only on specific devices:
curl -X POST http://localhost:8080/api/profiles/holiday/apply \
  -H "Content-Type: application/json" \
  -d '{"devices": ["XXXXXXXX-..."], "apply_schedules": false}'
```

---

## Scenarios (Presets)

A scenario assigns a different profile to each device. Applying it writes all profiles simultaneously with live SSE progress.

### `GET /api/presets`
List all scenarios.

**Response:**
```json
[{ "id": 1, "name": "Wohnung Frühling", "assignments": { "XXXXXXXX-...": "spring" } }]
```

### `POST /api/presets`
Create a scenario.

**Body:**
```json
{
  "name": "Wohnung Frühling",
  "assignments": {
    "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX": "spring",
    "YYYYYYYY-YYYY-YYYY-YYYY-YYYYYYYYYYYY": "summer"
  }
}
```
**Response:** `201 Created`

### `GET /api/presets/{id}`
Get a single scenario. **Response:** scenario object

### `PUT /api/presets/{id}`
Update scenario name and/or assignments.

### `DELETE /api/presets/{id}`
Delete scenario. **Response:** `204 No Content`

### `POST /api/presets/{id}/apply`
Apply scenario — returns a **Server-Sent Events** stream.

```bash
curl -N -X POST http://localhost:8080/api/presets/1/apply
```

**SSE Events:**
```
event: progress
data: {"address": "XXXXXXXX-...", "profile": "spring", "index": 0, "total": 3}

event: result
data: {"address": "XXXXXXXX-...", "status": "ok"}

event: done
data: {"preset": "Wohnung Frühling", "results": {"XXXXXXXX-...": "ok", ...}}
```

---

## Scheduler (Zeitplan)

Automatically apply a scenario or profile at set times and days of the week.

### `GET /api/auto-triggers`
List all triggers.

**Response:**
```json
[{
  "id": 1,
  "name": "Morgens warm",
  "type": "scenario",
  "target_id": "1",
  "days": ["mon", "tue", "wed", "thu", "fri"],
  "time_hm": "07:00",
  "enabled": true,
  "last_run": "2026-03-16T07:00:00",
  "next_run": "2026-03-17T07:00:00",
  "created_at": "2026-03-15T10:00:00"
}]
```

### `POST /api/auto-triggers`
Create a trigger.

**Body:**
```json
{
  "name": "Morgens warm",
  "type": "scenario",
  "target_id": "1",
  "days": ["mon", "tue", "wed", "thu", "fri"],
  "time_hm": "07:00",
  "enabled": true
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `type` | `"scenario"` / `"profile"` | What to apply |
| `target_id` | scenario ID (string) or profile name | Target |
| `days` | `["daily"]` or `["mon","tue",...]` | Which days |
| `time_hm` | `"HH:MM"` | Time of day |

**Response:** `201 Created`

### `PUT /api/auto-triggers/{id}`
Update a trigger. Same body as POST.

### `DELETE /api/auto-triggers/{id}`
Delete a trigger. **Response:** `204 No Content`

### `POST /api/auto-triggers/{id}/run`
Execute a trigger immediately (ignores schedule).

---

## Discovery

### `GET /api/discovery/stream?timeout=10`
BLE scan — returns a **Server-Sent Events** stream of found devices. Ends after `timeout` seconds.

```bash
curl -N "http://localhost:8080/api/discovery/stream?timeout=15"
```

**SSE Events:**
```
event: device
data: {"address": "XXXXXXXX-...", "name": "Comet Blue", "rssi": -65, "verified": true}

event: progress
data: {"elapsed": 3.5, "total": 15.0}

event: done
data: {"found": 7}

event: error
data: {"message": "scan_in_progress"}
```

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `timeout` | `10.0` | Scan duration in seconds (3–60) |

### `GET /api/discovery/locator`
Continuous RSSI locator — streams sorted RSSI snapshots every second until the client disconnects. Useful for physically locating thermostats by walking towards the strongest signal.

> Only one BLE scan can run at a time. Starting the locator while a regular scan is active (or vice versa) returns an `error` event.

```bash
curl -N "http://localhost:8080/api/discovery/locator"
```

**SSE Events:**
```
event: rssi
data: [
  {"address": "XXXXXXXX-...", "name": "Comet Blue", "rssi": -65, "label": "Küche"},
  {"address": "YYYYYYYY-...", "name": "Comet Blue", "rssi": -78, "label": null}
]

event: error
data: {"message": "scan_in_progress"}
```

Each `rssi` event contains all currently seen CometBlue devices, sorted strongest-first. `label` is the configured device name from the database (or `null` if not yet added).

Close the connection (Ctrl-C / disconnect) to stop the scan.

### `GET /api/discovery/known`
All devices ever found via scan (persisted in DB).

**Response:**
```json
[{
  "address": "XXXXXXXX-...",
  "name": "Comet Blue",
  "rssi": -65,
  "mac_address": "XX:XX:XX:XX:XX:XX",
  "last_seen": "2026-03-16T09:00:00",
  "configured": true
}]
```

---

## History

### `GET /api/history/{address}`
Temperature and battery history for a device.

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `hours=24` | Relative time window (from now) |
| `from=2026-03-01T00:00:00` | Absolute start (ISO 8601) |
| `to=2026-03-16T23:59:59` | Absolute end (ISO 8601) |
| `limit=500` | Max records (default 500) |

**Response:**
```json
{
  "address": "XXXXXXXX-...",
  "count": 288,
  "records": [
    {
      "recorded_at": "2026-03-16T08:00:00",
      "temp_current": 20.5,
      "temp_comfort": 19.0,
      "temp_eco": 18.0,
      "battery": 78
    }
  ]
}
```

### `GET /api/history`
Combined history for all devices (used by the Monitor chart).

**Query parameters:** `hours=24`, `limit=1000`

**Response:** `[{ "address", "name", "records": [...] }]`

---

## Settings

### `PATCH /api/settings/auto_poll`
Enable or disable automatic background polling.

**Body:** `{ "enabled": true }`
**Response:** `{ "auto_poll": true }`

### `PUT /api/settings/poll-interval`
Update the poll interval at runtime (minimum 60 seconds, recommended ≥ 900).

**Body:** `{ "poll_interval": 900 }`
**Response:** `{ "poll_interval": 900, "next_poll": "2026-03-16T08:25:00" }`

> ⚠️ **Firmware warning:** Polling too frequently freezes CometBlue devices. Recovery requires removing and reinserting the battery. Recommended minimum: **15 minutes (900 s)**.

---

## System

### `GET /api/status`
Service status overview.

**Response:**
```json
{
  "status": "ok",
  "devices": 7,
  "poll_interval": 900,
  "next_poll": "2026-03-16T08:25:00+01:00",
  "auto_poll": false
}
```
