# CometBlue Control

Cross-platform management system for **CometBlue / Comet Blue** Bluetooth Low Energy radiator thermostats. Runs on macOS, Linux, and Raspberry Pi.

Provides a REST API, optional Web UI, MCP server (for AI integration), and CLI — all from a single Python package.

---

## Features

- **Automatic BLE discovery** — scans and identifies CometBlue devices
- **Full thermostat control** — temperatures, weekly schedules, holiday slots, time sync
- **Child lock control** — toggle per device or bulk-set all devices at once; optionally part of a profile
- **Background polling** — regularly reads all configured devices (configurable interval, on/off toggle persisted in DB)
- **Alert system** — banner warnings for low battery, connection errors, and devices not yet polled
- **Heating profiles** — Winter, Summer, Spring, Holiday, Aus, Weekend, Weekday; optional child lock per profile
- **Scenes (Szenen/Presets)** — assign different profiles to different devices, save as named scenes, apply all at once with live progress
- **Temperature history / monitoring** — chart with dual Y-axis (temperature + battery)
- **REST API** — complete OpenAPI-documented HTTP API with SSE streaming for long-running operations
- **Web UI** — single-page dashboard (Alpine.js + Tailwind, no build step required)
- **MCP server** — Model Context Protocol for AI assistant integration
- **CLI** — command-line tools for scripting
- **SQLite storage** — devices, history, settings, presets
- **MAC-based identity** — stores device MAC after first poll; auto-resolves new UUID after battery swap (macOS)
- **Platform-agnostic** — uses `bleak` for BLE (replaces Linux-only `gattlib`)

---

## Requirements

- Python 3.10+
- Bluetooth 4.0+ adapter (built-in or USB dongle)
- On Linux/RPi: BlueZ (`sudo apt install bluetooth bluez`)
- On macOS: Core Bluetooth (built-in, Bluetooth permission required)

---

## Installation

### Quick install (recommended)

```bash
git clone https://github.com/yourname/cometblue-control
cd cometblue-control

# Core + API + Web UI (no extra dependencies needed):
./install.sh

# With MCP server support:
./install.sh --with-mcp

# On Linux/RPi with systemd auto-start:
./install.sh --with-mcp --systemd
```

### Manual install

```bash
cd cometblue-control
python3 -m venv .venv
source .venv/bin/activate         # Linux/macOS
# .venv\Scripts\activate          # Windows

pip install -e "."                # core + API + UI
pip install -e ".[mcp]"           # + MCP server
pip install -e ".[mcp,dev]"       # + dev/test tools
```

---

## Quick Start

```bash
source .venv/bin/activate

# 1. Start the server
cometblue-control serve
#    Web UI:  http://localhost:8080
#    API docs: http://localhost:8080/docs

# 2. Scan for devices
cometblue-control discover

# 3. Check device status (once added via UI or API)
cometblue-control status E0:E5:CF:C1:D4:3F

# 4. List available profiles
cometblue-control list-profiles
```

---

## Configuration

The config file is created at `~/.cometblue/config.yaml` on first run. Edit it to adjust settings:

```yaml
host: "0.0.0.0"
port: 8080
poll_interval: 300       # seconds between polls (default: 5 min)

bluetooth:
  adapter: null          # null = system default, or "hci0" on Linux
  scan_timeout: 10

ui:
  enabled: true

log_level: "INFO"
```

Runtime settings (e.g. `auto_poll`) are stored in the database and survive restarts. They can be toggled from the Web UI nav bar or via the settings API.

### Profiles

Profiles live in `~/.cometblue/profiles/`. Each YAML file defines temperature setpoints, an optional child lock setting, and optional weekly schedules:

```yaml
# ~/.cometblue/profiles/my_profile.yaml
name: My Profile
comfort_temp: 22.0       # heating "on" temperature
eco_temp: 17.0           # heating "off" / reduced temperature
manual_temp: 20.0        # manual override temperature
child_lock: false        # true = lock on, false = lock off, omit = don't change
schedules:
  monday:
    - {start: "07:00", end: "12:00"}
    - {start: "12:10", end: "19:00"}
  tuesday:
    - {start: "07:00", end: "12:00"}
    - {start: "12:10", end: "19:00"}
  # ... wednesday through sunday
  saturday:
    - {start: "07:00", end: "12:00"}
    - {start: "12:10", end: "19:00"}
  sunday:
    - {start: "07:00", end: "12:00"}
    - {start: "12:10", end: "19:00"}
```

Up to 4 time periods per day. Omit a day to leave its schedule unchanged when applying. Omit `child_lock` to leave it unchanged.

**Built-in profiles:**

| Profile | Heizen | Absenken | Notes |
|---------|--------|----------|-------|
| `winter` | 22.5 °C | 19.0 °C | Standard winter heating |
| `summer` | 19.0 °C | 15.0 °C | Light summer mode |
| `spring` | 19.0 °C | 18.0 °C | Spring / mild weather |
| `holiday` | 15.0 °C | 10.0 °C | Away from home |
| `aus` | 8.0 °C | 8.0 °C | Frost protection / off |
| `weekend` | 22.0 °C | 17.0 °C | Extended weekend times |
| `weekday` | 22.0 °C | 17.0 °C | Compact weekday times |

---

## Web UI

Start the server and open **http://localhost:8080**.

| Page | Description |
|---|---|
| **Dashboard** | Live status cards for all devices — temperatures, battery, RSSI, child lock toggle |
| **Monitor** | Temperature + battery history chart (dual Y-axis) per device |
| **Devices** | Full device list — poll, set temps, schedules, child lock, rename, reset data |
| **Profiles** | View, create, edit and apply heating profiles with schedule and child lock settings |
| **Szenen** | Named scenes: assign one profile per device, apply all at once with live progress bar |
| **Discovery** | BLE scan, add found devices with one click |

### Nav bar

- **Auto-poll toggle** — enable/disable background polling (persisted in DB)
- **Poll all button** — trigger an immediate poll of all devices
- **Alert badge** — shows count of active alerts (low battery, errors, unpolled devices)

### Alert banner

Shown automatically when:
- Battery ≤ 10% → critical (red)
- Battery ≤ 20% → warning (yellow)
- Device has a connection error
- Device has never been polled

> **Note on battery levels:** CometBlue reports raw voltage without calibration. New batteries typically show ~80–90%, not 100%.

### Child lock

- Click `🔒 AN` / `🔓 AUS` on any device card to toggle instantly
- On the Devices page: **"🔒 Alle sperren"** / **"🔓 Alle entsperren"** buttons to bulk-set all devices
- Set `child_lock: true/false` in a profile to apply it automatically when the profile is applied

---

## Scenes (Szenen/Presets)

A scene stores a mapping of device → profile. Applying a scene writes each profile to its assigned device simultaneously, with a live progress bar showing per-device status.

**Example use case:** "Winter" scene → Wohnzimmer=winter, Schlafzimmer=winter, Bad=winter, Küche=spring.

Scenes are managed in the **Szenen** tab of the Web UI or via the REST API.

---

## REST API

Full OpenAPI documentation available at **http://localhost:8080/docs** when the server is running.

### Device Management

```
GET    /api/devices                          List all configured devices
POST   /api/devices                          Add a device
GET    /api/devices/{address}                Get device details
PATCH  /api/devices/{address}                Update device (name, pin, adapter)
DELETE /api/devices/{address}                Remove device (history is kept)
GET    /api/devices/{address}/status         Latest cached status (instant)
POST   /api/devices/{address}/poll           Trigger immediate BLE poll
POST   /api/devices/{address}/reset          Clear cached status + history for device
PATCH  /api/devices/{address}/flags          Set child lock (and other flags)
POST   /api/devices/set-child-lock           Bulk set child lock on all or specific devices
```

**Bulk child lock example:**
```bash
# Lock all devices:
curl -X POST http://localhost:8080/api/devices/set-child-lock \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "addresses": ["all"]}'

# Unlock specific devices:
curl -X POST http://localhost:8080/api/devices/set-child-lock \
  -H "Content-Type: application/json" \
  -d '{"enabled": false, "addresses": ["E0:E5:CF:C1:D4:3F", "AA:BB:CC:DD:EE:FF"]}'
```

**Set child lock on one device:**
```bash
curl -X PATCH http://localhost:8080/api/devices/E0:E5:CF:C1:D4:3F/flags \
  -H "Content-Type: application/json" \
  -d '{"child_lock": true}'
```

### Temperature Control

```
GET  /api/devices/{address}/temperatures       Cached temperatures
PUT  /api/devices/{address}/temperatures       Set temperature setpoints
POST /api/devices/{address}/sync-time          Write current time to device
```

**Set temperatures example:**
```bash
curl -X PUT http://localhost:8080/api/devices/E0:E5:CF:C1:D4:3F/temperatures \
  -H "Content-Type: application/json" \
  -d '{"comfort": 22.0, "eco": 17.0, "manual": 20.0}'
```

### Schedules

```
GET  /api/devices/{address}/schedules          Full weekly schedule (live from device)
PUT  /api/devices/{address}/schedules          Set full week
PUT  /api/devices/{address}/schedules/{day}    Set one day (monday–sunday)
```

**Set one day example:**
```bash
curl -X PUT http://localhost:8080/api/devices/E0:E5:CF:C1:D4:3F/schedules/monday \
  -H "Content-Type: application/json" \
  -d '{"periods": [{"start": "07:00", "end": "12:00"}, {"start": "12:10", "end": "19:00"}]}'
```

### Holidays

```
GET    /api/devices/{address}/holidays          All 8 holiday slots
PUT    /api/devices/{address}/holidays/{slot}   Set slot (1–8)
DELETE /api/devices/{address}/holidays/{slot}   Clear slot
```

**Set holiday example:**
```bash
curl -X PUT http://localhost:8080/api/devices/E0:E5:CF:C1:D4:3F/holidays/1 \
  -H "Content-Type: application/json" \
  -d '{"start": "2026-12-24T00:00:00", "end": "2027-01-02T23:59:00", "temperature": 15.0, "active": true}'
```

### Profiles

```
GET  /api/profiles                     List profiles
GET  /api/profiles/{name}              Get profile details (includes child_lock if set)
PUT  /api/profiles/{name}              Create/update profile
POST /api/profiles/{name}/apply        Apply profile to devices
```

**Apply profile example:**
```bash
# Apply to all devices with schedules:
curl -X POST http://localhost:8080/api/profiles/winter/apply \
  -H "Content-Type: application/json" \
  -d '{"devices": ["all"], "apply_schedules": true}'

# Apply temperatures only (no schedule change) to specific devices:
curl -X POST http://localhost:8080/api/profiles/holiday/apply \
  -H "Content-Type: application/json" \
  -d '{"devices": ["E0:E5:CF:C1:D4:3F"], "apply_schedules": false}'
```

### Scenes (Presets)

```
GET    /api/presets                     List all scenes
POST   /api/presets                     Create scene  { name, assignments: {address: profile} }
GET    /api/presets/{id}                Get scene details
PUT    /api/presets/{id}                Update scene
DELETE /api/presets/{id}                Delete scene
POST   /api/presets/{id}/apply          Apply scene (SSE stream — progress per device)
```

The `/apply` endpoint returns a **Server-Sent Events** stream:

```
event: progress
data: {"address": "E0:E5:CF...", "profile": "winter", "index": 0, "total": 3}

event: result
data: {"address": "E0:E5:CF...", "status": "ok"}

event: done
data: {"preset": "Winter Abend", "results": {"E0:E5:CF...": "ok", ...}}
```

**Create and apply a scene example:**
```bash
# Create scene
curl -X POST http://localhost:8080/api/presets \
  -H "Content-Type: application/json" \
  -d '{"name": "Winter Abend", "assignments": {"E0:E5:CF:C1:D4:3F": "winter", "AA:BB:CC:DD:EE:FF": "spring"}}'

# Apply scene (streamed)
curl -N http://localhost:8080/api/presets/1/apply -X POST
```

### Discovery

```
POST /api/discovery/scan?timeout=10    BLE scan (SSE stream — device found events)
GET  /api/discovery/known              Known/persisted scan results
```

### History

```
GET /api/history/{address}             Temperature + battery history
    ?from=2026-03-01T00:00:00          Optional: start datetime (ISO)
    &to=2026-03-14T23:59:59            Optional: end datetime (ISO)
    &limit=500                          Optional: max records (default 500)
```

### Settings

```
GET   /api/settings/auto_poll          Get auto-poll setting
PATCH /api/settings/auto_poll          Set auto-poll  { "enabled": true/false }
```

### System

```
GET /api/status                        Service status, device count, next poll time, auto_poll flag
```

---

## MCP Server

The MCP server allows AI assistants (Claude) to control thermostats directly.

### Setup with Claude Code

Add to your Claude Code MCP config (`~/.claude/claude_code_config.json`):

```json
{
  "mcpServers": {
    "cometblue": {
      "command": "/path/to/cometblue-control/.venv/bin/cometblue-control",
      "args": ["mcp"]
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|---|---|
| `list_devices` | List all configured devices with last known status |
| `get_device_status` | Get current temperature and battery for a device |
| `set_temperature` | Set comfort/eco/manual temperature setpoints |
| `apply_profile` | Apply a heating profile to all or specific devices |
| `discover_devices` | BLE scan for CometBlue devices |
| `get_schedule` | Read weekly heating schedule from device |
| `set_schedule` | Write schedule for a specific day |
| `get_holidays` | Read all holiday slots from device |
| `set_holiday` | Set a holiday period with temperature |
| `get_history` | Query historical temperature data |
| `sync_time` | Synchronize device clock to system time |
| `list_profiles` | List available heating profiles |

---

## CLI Reference

```bash
cometblue-control [OPTIONS] COMMAND

Options:
  -c, --config-file PATH   Custom config file
  -l, --log-level TEXT     DEBUG | INFO | WARNING | ERROR

Commands:
  serve           Start API server (+ Web UI)
  mcp             Start MCP server (stdio)
  discover        Scan for CometBlue devices
  status ADDRESS  Poll device and show status
  list-profiles   List available profiles
```

**Examples:**

```bash
# Start with custom port
cometblue-control serve --port 9000

# Discover with longer timeout
cometblue-control discover --timeout 20

# Get device status as JSON
cometblue-control status E0:E5:CF:C1:D4:3F --json

# Start MCP (for Claude Code integration)
cometblue-control mcp
```

---

## Raspberry Pi Setup

```bash
# 1. Install BlueZ
sudo apt update && sudo apt install -y bluetooth bluez python3 python3-venv git

# 2. Enable Bluetooth
sudo systemctl enable bluetooth && sudo systemctl start bluetooth

# 3. Clone and install
git clone https://github.com/yourname/cometblue-control
cd cometblue-control
./install.sh --with-mcp --systemd

# 4. Start service
sudo systemctl start cometblue
sudo systemctl status cometblue

# 5. View logs
journalctl -u cometblue -f
```

Access the UI from another device: `http://<raspberry-pi-ip>:8080`

### Bluetooth permissions on Linux

If you get permission errors with Bluetooth:

```bash
sudo usermod -aG bluetooth $USER
# Log out and back in, then retry
```

---

## BLE Protocol Reference

CometBlue uses a proprietary BLE GATT profile alongside standard Device Information Service characteristics.

### UUIDs

| UUID | Name | R/W | Description |
|---|---|---|---|
| `47e9ee01-47e9-11e4-8939-164230d1df67` | datetime | R/W | 5 bytes: min, hour, day, month, year-2000 |
| `47e9ee2a-47e9-11e4-8939-164230d1df67` | flags | R/W | Device status flags (child lock, manual mode, …) |
| `47e9ee2b-47e9-11e4-8939-164230d1df67` | temperatures | R/W | 7 signed bytes (÷2 = °C) |
| `47e9ee2c-47e9-11e4-8939-164230d1df67` | battery | R | 1 byte (255 = unavailable) |
| `47e9ee2d-47e9-11e4-8939-164230d1df67` | firmware_revision2 | R | String |
| `47e9ee2e-47e9-11e4-8939-164230d1df67` | lcd_timer | R/W | LCD timeout |
| `47e9ee30-47e9-11e4-8939-164230d1df67` | pin | W | PIN authentication (4-byte LE) |
| `47e9ee10` … `47e9ee16` | day[1–7] | R/W | Weekly schedule, 8 bytes each |
| `47e9ee20` … `47e9ee27` | holiday[1–8] | R/W | Holiday slots, 9 bytes each |

### Temperature encoding

7 bytes, each value × 2 = °C. Use `0x80` as placeholder for "do not change":

```
byte 0: current temperature (read-only)
byte 1: manual setpoint
byte 2: comfort setpoint
byte 3: eco setpoint
byte 4: temperature offset
byte 5: window open flag
byte 6: window open duration (minutes)
```

### Flags encoding

3 bytes. Relevant bits:

```
byte 0, bit 7 (0x80): child lock  — 0x80=ON, 0x00=OFF (confirmed empirically)
byte 0, bit 0 (0x01): DST active
byte 0, bit 2 (0x04): anti-frost
byte 1, bit 1 (0x02): manual mode
```

Reading and writing flags requires PIN authentication first.

### Schedule encoding

8 bytes = 4 × (start, end), each in 10-minute increments (0 = 00:00, 144 = 24:00). `0xFF` = period disabled.

### PIN authentication

Write a 4-byte little-endian encoded PIN to the `pin` characteristic before accessing protected operations. Example: PIN `1234` → `0xD2040000`.

### macOS UUID behaviour

On macOS, CoreBluetooth assigns a random UUID per device instead of exposing the real MAC address. This UUID changes after a battery replacement. CometBlue Control handles this automatically:

1. After the first successful (authenticated) poll, the real MAC is read from the System ID characteristic and stored.
2. On subsequent polls, if the stored UUID is not found, a BLE scan is run to find the device by MAC address, and the UUID is updated in the database automatically.

---

## Project Structure

```
cometblue-control/
├── cometblue/
│   ├── protocol.py          BLE encode/decode for all characteristics
│   ├── device.py            Async BLE device class (bleak), auto-MAC resolution
│   ├── discovery.py         BLE scan + CometBlue identification + streaming
│   ├── database.py          SQLite: devices, status cache, history, settings, presets
│   ├── scheduler.py         Background polling (APScheduler), auto_poll check
│   ├── profiles.py          Profile load/save/apply (incl. child_lock)
│   ├── config.py            Config file loading
│   ├── cli.py               Click CLI
│   ├── api/
│   │   ├── app.py           FastAPI application factory
│   │   ├── models.py        Pydantic request/response models
│   │   └── routes/
│   │       ├── devices.py   Device CRUD, poll, flags, bulk child-lock
│   │       ├── temperatures.py
│   │       ├── schedules.py
│   │       ├── holidays.py
│   │       ├── profiles.py
│   │       ├── presets.py   Scenes/presets CRUD + SSE apply
│   │       ├── discovery.py SSE BLE scan stream
│   │       ├── history.py
│   │       └── settings.py  auto_poll and future runtime settings
│   └── mcp/
│       └── server.py        MCP server (12 tools)
├── ui/
│   └── index.html           Web UI (Alpine.js + Tailwind, no build needed)
├── config/
│   ├── config.yaml          Default configuration
│   └── profiles/            Default heating profiles (winter, summer, spring, holiday, aus, weekend, weekday)
├── systemd/
│   └── cometblue.service    systemd unit file
├── install.sh               Installation helper
└── pyproject.toml           Package definition
```

---

## Data Storage

All data is stored in `~/.cometblue/cometblue.db` (SQLite).

| Table | Contents |
|---|---|
| `devices` | Configured devices (address, name, PIN, adapter, mac_address) |
| `device_status` | Latest polled status per device (temperatures, battery, RSSI, child_lock, …) |
| `history` | Time-series temperature and battery readings |
| `scan_results` | Persisted BLE scan results (address, name, RSSI, MAC) |
| `settings` | Key/value runtime settings (`auto_poll`, …) |
| `presets` | Named scenes (name + device→profile assignment JSON) |

Deleting a device only removes it from the `devices` table — history and status are preserved so data survives a re-add. Use **"Daten zurücksetzen"** (reset) in the device edit modal or `POST /api/devices/{address}/reset` to clear history and cached status for a device.

---

## Troubleshooting

**"No devices found" during scan**
- Check Bluetooth is on and the thermostat is within range (~10m)
- On macOS: grant Bluetooth permission to Terminal / your shell
- On Linux: check `sudo systemctl status bluetooth` and BlueZ version

**"BLE error" when connecting**
- The thermostat only allows one connection at a time — wait a few seconds and retry
- If another app (e.g. the official CometBlue app) has an open connection, close it first
- Try increasing the connection timeout in `config.yaml`

**Wrong PIN / auth failed**
- The PIN can be set offline in the device edit modal (saved to DB without connecting)
- Use "Offline speichern (ohne Test)" in the PIN dialog if the device is currently unreachable

**Device UUID changed after battery replacement (macOS)**
- After the new batteries are inserted and the device is rediscovered, set the correct PIN
- On the first successful poll the new UUID and MAC are stored automatically
- If needed, use the **"Zuordnen"** button in the Devices page to manually re-link the UUID

**Battery shows 80–90% on new batteries**
- This is expected — CometBlue reports raw voltage without calibration. A reading of ~80–90% corresponds to fully charged batteries.

**Permission denied on Linux**
- Add your user to the `bluetooth` group: `sudo usermod -aG bluetooth $USER`

**Web UI shows "No devices"**
- Add a device first via the Discover page or `POST /api/devices`
- Check the server logs for BLE errors

---

## Sources

- Original Python library: https://github.com/im-0/cometblue
- BLE protocol documentation: https://www.torsten-traenkner.de/wissen/smarthome/heizung.php

---

## License

MIT
