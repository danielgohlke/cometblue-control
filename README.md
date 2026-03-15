# CometBlue Control

Cross-platform management system for **CometBlue / Comet Blue** Bluetooth Low Energy radiator thermostats. Runs on macOS, Linux, and Raspberry Pi.

Provides a REST API, optional Web UI, MCP server (for AI integration), and CLI — all from a single Python package.

---

## Features

- **Automatic BLE discovery** — scans and identifies CometBlue devices
- **Full thermostat control** — temperatures, weekly schedules, holiday slots, time sync
- **Background polling** — regularly reads all configured devices (configurable interval)
- **Heating profiles** — Winter, Summer, Holiday, Weekend, Weekday (customizable YAML)
- **REST API** — complete OpenAPI-documented HTTP API
- **Web UI** — single-page dashboard (no build step required)
- **MCP server** — Model Context Protocol for AI assistant integration
- **CLI** — command-line tools for scripting
- **SQLite history** — stores temperature readings over time
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

### Profiles

Profiles live in `~/.cometblue/profiles/`. Each YAML file defines temperature setpoints and an optional weekly schedule:

```yaml
# ~/.cometblue/profiles/my_profile.yaml
name: My Profile
comfort_temp: 22.0       # heating "on" temperature
eco_temp: 17.0           # heating "off" / reduced temperature
manual_temp: 20.0        # manual override temperature
schedules:
  monday:
    - {start: "06:30", end: "08:00"}
    - {start: "17:00", end: "22:00"}
  tuesday:
    - {start: "06:30", end: "22:00"}
  # ... wednesday through sunday
  saturday:
    - {start: "08:00", end: "23:00"}
  sunday:
    - {start: "08:00", end: "22:00"}
```

Up to 4 time periods per day. Omit a day to leave it unchanged when applying.

**Default profiles:** `winter`, `summer`, `holiday`, `weekend`, `weekday`

---

## Web UI

Start the server and open **http://localhost:8080**.

| Page | Description |
|---|---|
| Dashboard | Live status cards for all devices, quick temperature controls |
| Devices | Full device list with actions (poll, set temps, schedule, remove) |
| Profiles | View and apply heating profiles to all devices |
| Discover | BLE scan, add found devices with one click |

---

## REST API

Full OpenAPI documentation available at **http://localhost:8080/docs** when the server is running.

### Device Management

```
GET    /api/devices                    List all configured devices
POST   /api/devices                    Add a device
GET    /api/devices/{address}          Get device details
DELETE /api/devices/{address}          Remove a device
GET    /api/devices/{address}/status   Latest cached status (instant)
POST   /api/devices/{address}/poll     Trigger immediate BLE poll
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
  -d '{"periods": [{"start": "06:30", "end": "08:00"}, {"start": "17:00", "end": "22:00"}]}'
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
GET  /api/profiles/{name}              Get profile details
PUT  /api/profiles/{name}              Create/update profile
POST /api/profiles/{name}/apply        Apply profile to devices
```

**Apply profile example:**
```bash
# Apply to all devices:
curl -X POST http://localhost:8080/api/profiles/winter/apply \
  -H "Content-Type: application/json" \
  -d '{"devices": ["all"], "apply_schedules": true}'

# Apply to specific devices only:
curl -X POST http://localhost:8080/api/profiles/holiday/apply \
  -H "Content-Type: application/json" \
  -d '{"devices": ["E0:E5:CF:C1:D4:3F", "AA:BB:CC:DD:EE:FF"], "apply_schedules": false}'
```

### Discovery

```
POST /api/discovery/scan?timeout=10    BLE scan, returns found devices
```

### History

```
GET /api/history/{address}             Temperature history
    ?from=2026-03-01T00:00:00          Optional: start datetime (ISO)
    &to=2026-03-14T23:59:59            Optional: end datetime (ISO)
    &limit=500                          Optional: max records (default 500)
```

### System

```
GET /api/status                        Service status, device count, next poll time
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
| `47e9ee2a-47e9-11e4-8939-164230d1df67` | flags | R | Device status flags |
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

### Schedule encoding

8 bytes = 4 × (start, end), each in 10-minute increments (0 = 00:00, 144 = 24:00). `0xFF` = period disabled.

### PIN authentication

Write a 4-byte little-endian encoded PIN to the `pin` characteristic before accessing protected operations. Example: PIN `1234` → `0xD2040000`.

---

## Project Structure

```
cometblue-control/
├── cometblue/
│   ├── protocol.py          BLE encode/decode for all characteristics
│   ├── device.py            Async BLE device class (bleak)
│   ├── discovery.py         BLE scan + CometBlue identification
│   ├── database.py          SQLite: devices, status cache, history
│   ├── scheduler.py         Background polling (APScheduler)
│   ├── profiles.py          Profile load/save/apply
│   ├── config.py            Config file loading
│   ├── cli.py               Click CLI
│   ├── api/
│   │   ├── app.py           FastAPI application factory
│   │   ├── models.py        Pydantic request/response models
│   │   └── routes/          Route modules per resource
│   └── mcp/
│       └── server.py        MCP server (12 tools)
├── ui/
│   └── index.html           Web UI (Alpine.js + Tailwind, no build needed)
├── config/
│   ├── config.yaml          Default configuration
│   └── profiles/            Default heating profiles (5×)
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
| `devices` | Configured devices (address, name, PIN, adapter) |
| `device_status` | Latest polled status per device (cached) |
| `history` | Time-series temperature and battery readings |

---

## Troubleshooting

**"No devices found" during scan**
- Check Bluetooth is on and the thermostat is within range (~10m)
- On macOS: grant Bluetooth permission to Terminal / your shell
- On Linux: check `sudo systemctl status bluetooth` and BlueZ version

**"BLE error" when connecting**
- The thermostat may be busy (it only allows one connection at a time)
- Try increasing the connection timeout in `config.yaml`
- If PIN-protected, make sure the PIN is set correctly for the device

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
