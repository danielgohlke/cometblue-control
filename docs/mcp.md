# MCP Server

CometBlue Control includes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that lets AI assistants like **Claude** control your thermostats directly — reading temperatures, applying profiles, managing schedules, and more.

The MCP server supports two transports:
- **stdio** — for local use (Claude Code on the same machine)
- **HTTP/SSE** — for remote use (Claude connecting over the network)

Both share the same SQLite database and BLE stack as the REST API and can run simultaneously.

---

## Setup

### Local (stdio transport)

#### Option 1 — Claude Code CLI (recommended)

```bash
claude mcp add cometblue -- /path/to/cometblue-control/.venv/bin/cometblue-control mcp
```

Replace `/path/to/cometblue-control` with your actual install path:
- macOS (local): `/Users/yourname/ClaudeProjects/cometblue-control`
- Linux / Raspberry Pi: `/opt/cometblue-control`

Verify the server is registered:
```bash
claude mcp list
```

#### Option 2 — JSON configuration

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "cometblue": {
      "type": "stdio",
      "command": "/path/to/cometblue-control/.venv/bin/cometblue-control",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

> **Note:** Both `"type": "stdio"` and `"env": {}` are required fields.

#### Starting the server manually

```bash
source .venv/bin/activate
cometblue-control mcp
```

The server reads from stdin and writes to stdout — it is started automatically by Claude Code when needed.

---

### Remote (HTTP/SSE transport)

Use this when the thermostat hardware (Bluetooth adapter) is on a different machine (e.g. a Raspberry Pi) and you want to control it from another device.

#### 1. Start the server on the host machine

```bash
cometblue-control mcp --transport http --host 0.0.0.0 --port 9090
```

The SSE endpoint is now available at `http://<host>:9090/sse`.

#### 2. Connect Claude Code to the remote server

```bash
claude mcp add --transport sse cometblue http://192.168.1.100:9090/sse
```

Or via JSON configuration in `~/.claude.json`:

```json
{
  "mcpServers": {
    "cometblue": {
      "type": "sse",
      "url": "http://192.168.1.100:9090/sse"
    }
  }
}
```

Replace `192.168.1.100` with the IP address of your host machine.

#### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--transport` | `stdio` | `stdio` or `http` |
| `--host` | `0.0.0.0` | Bind address (HTTP only) |
| `--port` / `-p` | `9090` | Port (HTTP only) |

> **Security note:** The HTTP server has no built-in authentication. Run it only on a trusted local network, or place it behind a reverse proxy with TLS and authentication.

#### Deploy via Ansible

The Ansible playbook in `deploy/deploy.yml` can install and manage the MCP service automatically:

```bash
# Deploy with MCP enabled
ansible-playbook -i deploy/inventory.ini deploy/deploy.yml -e install_mcp=true

# Update after code changes
ansible-playbook -i deploy/inventory.ini deploy/deploy.yml --tags update -e install_mcp=true

# Custom port
ansible-playbook -i deploy/inventory.ini deploy/deploy.yml -e install_mcp=true -e mcp_port=8765
```

| Variable | Default | Description |
|----------|---------|-------------|
| `install_mcp` | `true` | Install and start the MCP HTTP service |
| `mcp_port` | `9090` | Port for the SSE endpoint |

The playbook installs the `mcp` extra (`pip install -e '.[mcp]'`) and deploys a `cometblue-mcp.service` systemd unit alongside the existing `cometblue.service`.

---

## Verifying the integration

Ask Claude:

```
list my cometblue devices
```

Expected output:

```
⏺ cometblue - list_devices (MCP)

⏺ Here are your 7 CometBlue devices:

  ┌─────────────────────┬──────────────┬─────────┬───────────────────┐
  │        Name         │ Current Temp │ Battery │      Status       │
  ├─────────────────────┼──────────────┼─────────┼───────────────────┤
  │ Bad                 │ 20.5°C       │ 29%     │ Error (not found) │
  ├─────────────────────┼──────────────┼─────────┼───────────────────┤
  │ Kinderzimmer Links  │ 18.5°C       │ 65%     │ Error (not found) │
  ├─────────────────────┼──────────────┼─────────┼───────────────────┤
  │ Kinderzimmer Rechts │ 18.5°C       │ 66%     │ Timeout           │
  ├─────────────────────┼──────────────┼─────────┼───────────────────┤
  │ Küche               │ 17.5°C       │ 87%     │ Error (not found) │
  ├─────────────────────┼──────────────┼─────────┼───────────────────┤
  │ Schlafzimmer        │ 19.5°C       │ 78%     │ OK                │
  ├─────────────────────┼──────────────┼─────────┼───────────────────┤
  │ Wohnzimmer Links    │ 20.5°C       │ 78%     │ OK                │
  ├─────────────────────┼──────────────┼─────────┼───────────────────┤
  │ Wohnzimmer Rechts   │ 20.0°C       │ 71%     │ OK                │
  └─────────────────────┴──────────────┴─────────┴───────────────────┘

  Notable: 4 devices have connection errors and show cached data from their
  last successful poll. The Bad thermostat also has a low battery (29%).
```

> Devices with errors display the last cached values. A manual poll or enabling auto-poll will refresh them.

---

## Available Tools

### `list_devices`
List all configured devices with last known temperature and battery.

**Input:** none

**Output:**
```json
[{
  "address": "XXXXXXXX-...",
  "name": "Wohnzimmer",
  "status": {
    "temp_current": 20.5,
    "temp_comfort": 19.0,
    "temp_eco": 18.0,
    "battery": 78,
    "child_lock": false,
    "error": null,
    "polled_at": "2026-03-16T08:05:00"
  }
}]
```

---

### `get_device_status`
Get current status for a specific device (cached — no BLE required).

**Input:** `{ "address": "XXXXXXXX-..." }`

**Output:** Same status object as in `list_devices`.

---

### `set_temperature`
Set temperature setpoints via BLE.

**Input:**
```json
{
  "address": "XXXXXXXX-...",
  "comfort": 22.0,
  "eco": 17.0
}
```

All temperature fields are optional — omitted values stay unchanged.

| Field | Range | Description |
|-------|-------|-------------|
| `comfort` | 5–35 °C | Heating temperature (during schedule) |
| `eco` | 5–35 °C | Setback temperature (outside schedule) |
| `manual` | 5–35 °C | Manual override setpoint |

**Output:** `{ "status": "ok", "address": "..." }`

---

### `apply_profile`
Apply a heating profile to one or all devices.

**Input:**
```json
{
  "profile_name": "winter",
  "devices": ["all"],
  "apply_schedules": true
}
```

- `devices`: `["all"]` or a list of addresses
- `apply_schedules`: also write heating schedules to the device (default: `true`)

**Output:** `{ "profile": "winter", "results": { "XXXXXXXX-...": "ok" } }`

---

### `list_profiles`
List all available heating profiles.

**Input:** none

**Output:** `[{ "name": "winter" }, { "name": "summer" }, ...]`

---

### `list_scenarios`
List all saved scenarios (each assigns a profile per device).

**Input:** none

**Output:**
```json
[{
  "id": 1,
  "name": "Wohnung Frühling",
  "assignments": {
    "XXXXXXXX-...": "spring",
    "YYYYYYYY-...": "summer"
  }
}]
```

---

### `apply_scenario`
Apply a scenario by ID — writes the assigned profile to each device.

**Input:** `{ "scenario_id": 1 }`

**Output:**
```json
{
  "scenario": "Wohnung Frühling",
  "results": {
    "XXXXXXXX-...": "ok",
    "YYYYYYYY-...": "ok"
  }
}
```

---

### `discover_devices`
BLE scan for CometBlue devices in range.

**Input:** `{ "timeout": 10.0 }` (default: 10 seconds)

**Output:**
```json
[{ "address": "XXXXXXXX-...", "name": "Comet Blue", "rssi": -65, "verified": true }]
```

---

### `get_schedule`
Read the weekly heating schedule from a device via BLE.

**Input:** `{ "address": "XXXXXXXX-..." }`

**Output:**
```json
{
  "monday":    [{ "start": "07:00", "end": "12:00" }, { "start": "12:10", "end": "19:00" }],
  "tuesday":   [{ "start": "07:00", "end": "19:00" }],
  "saturday":  [{ "start": "08:00", "end": "22:00" }],
  "sunday":    [{ "start": "08:00", "end": "22:00" }]
}
```

---

### `set_schedule`
Write the heating schedule for one day.

**Input:**
```json
{
  "address": "XXXXXXXX-...",
  "day": "monday",
  "periods": [
    { "start": "07:00", "end": "12:00" },
    { "start": "12:10", "end": "19:00" }
  ]
}
```

- `day`: `monday`–`sunday`
- `periods`: up to 4 entries, times in 10-minute steps

**Output:** `{ "status": "ok" }`

---

### `get_holidays`
Read all 8 holiday slots from a device.

**Input:** `{ "address": "XXXXXXXX-..." }`

**Output:**
```json
[
  { "slot": 1, "active": true, "start": "2026-12-24T00:00:00", "end": "2027-01-02T23:59:00", "temperature": 15.0 },
  { "slot": 2, "active": false, "start": null, "end": null, "temperature": null }
]
```

---

### `set_holiday`
Set a holiday slot.

**Input:**
```json
{
  "address": "XXXXXXXX-...",
  "slot": 1,
  "start": "2026-12-24T00:00:00",
  "end": "2027-01-02T23:59:00",
  "temperature": 15.0
}
```

- `slot`: 1–8
- `temperature`: 5–35 °C

**Output:** `{ "status": "ok", "slot": 1 }`

---

### `get_history`
Query recent temperature and battery history.

**Input:** `{ "address": "XXXXXXXX-...", "limit": 50 }`

**Output:**
```json
{
  "address": "XXXXXXXX-...",
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

---

### `sync_time`
Synchronize the device clock to the current system time.

**Input:** `{ "address": "XXXXXXXX-..." }`

**Output:** `{ "status": "ok", "synced_at": "2026-03-16T08:10:00" }`

---

## Example Prompts

```
Set the Wohnzimmer thermostat to 21°C comfort, 17°C eco
Apply the winter profile to all devices
What is the current temperature in the Schlafzimmer?
Show me the heating schedule for Wohnzimmer Links
Set Wohnzimmer to holiday mode from December 24 to January 2 at 15°C
Apply the "Wohnung Frühling" scenario
```

---

## Notes

- `list_devices` and `get_device_status` read from the SQLite cache — **no BLE connection required**
- All other tools that interact with devices (`set_temperature`, `get_schedule`, etc.) **require an active BLE connection** to the device
- The MCP server and REST API server share the same database and can run simultaneously
- Background polling runs via APScheduler — the MCP server does not start the scheduler (only the REST API server does)
