"""MCP server for CometBlue Control (stdio and HTTP/SSE transport)."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    raise ImportError(
        "MCP SDK not installed. Run: pip install 'cometblue-control[mcp]'"
    )

from .. import database as db, config
from ..device import CometBlueDevice, poll_device
from .. import discovery, profiles as prof
from ..protocol import DaySchedule, TimePeriod, Holiday, DAY_NAMES, day_name_to_index

log = logging.getLogger(__name__)


def create_server() -> Server:
    server = Server("cometblue-control")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="list_devices",
                description="List all configured CometBlue thermostat devices and their last known status.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="get_device_status",
                description="Get the current status (temperature, battery) of a specific device.",
                inputSchema={
                    "type": "object",
                    "required": ["address"],
                    "properties": {
                        "address": {"type": "string", "description": "Bluetooth MAC address"},
                    },
                },
            ),
            types.Tool(
                name="set_temperature",
                description="Set temperature setpoints on a CometBlue thermostat.",
                inputSchema={
                    "type": "object",
                    "required": ["address"],
                    "properties": {
                        "address": {"type": "string"},
                        "comfort": {"type": "number", "description": "Comfort (high) temperature in °C"},
                        "eco": {"type": "number", "description": "Eco (low) temperature in °C"},
                        "manual": {"type": "number", "description": "Manual setpoint in °C"},
                    },
                },
            ),
            types.Tool(
                name="apply_profile",
                description="Apply a heating profile (e.g. winter, summer, holiday) to devices.",
                inputSchema={
                    "type": "object",
                    "required": ["profile_name"],
                    "properties": {
                        "profile_name": {"type": "string", "description": "Profile name (winter, summer, holiday, weekend, weekday)"},
                        "devices": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of device addresses, or ['all'] for all devices",
                            "default": ["all"],
                        },
                        "apply_schedules": {"type": "boolean", "default": True},
                    },
                },
            ),
            types.Tool(
                name="discover_devices",
                description="Scan for CometBlue thermostats via Bluetooth.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "timeout": {"type": "number", "default": 10.0, "description": "Scan duration in seconds"},
                    },
                },
            ),
            types.Tool(
                name="get_schedule",
                description="Get the weekly heating schedule for a device.",
                inputSchema={
                    "type": "object",
                    "required": ["address"],
                    "properties": {
                        "address": {"type": "string"},
                    },
                },
            ),
            types.Tool(
                name="set_schedule",
                description="Set the heating schedule for one day on a device.",
                inputSchema={
                    "type": "object",
                    "required": ["address", "day", "periods"],
                    "properties": {
                        "address": {"type": "string"},
                        "day": {"type": "string", "description": "Day name (monday, tuesday, ...)"},
                        "periods": {
                            "type": "array",
                            "description": "Up to 4 time periods [{start: HH:MM, end: HH:MM}]",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "start": {"type": "string"},
                                    "end": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            ),
            types.Tool(
                name="get_holidays",
                description="Get all holiday slots for a device.",
                inputSchema={
                    "type": "object",
                    "required": ["address"],
                    "properties": {"address": {"type": "string"}},
                },
            ),
            types.Tool(
                name="set_holiday",
                description="Set a holiday slot on a device.",
                inputSchema={
                    "type": "object",
                    "required": ["address", "slot", "start", "end", "temperature"],
                    "properties": {
                        "address": {"type": "string"},
                        "slot": {"type": "integer", "minimum": 1, "maximum": 8},
                        "start": {"type": "string", "description": "ISO datetime (YYYY-MM-DDTHH:MM:SS)"},
                        "end": {"type": "string"},
                        "temperature": {"type": "number"},
                    },
                },
            ),
            types.Tool(
                name="get_history",
                description="Get recent temperature history for a device.",
                inputSchema={
                    "type": "object",
                    "required": ["address"],
                    "properties": {
                        "address": {"type": "string"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            ),
            types.Tool(
                name="sync_time",
                description="Sync the current system time to a CometBlue device.",
                inputSchema={
                    "type": "object",
                    "required": ["address"],
                    "properties": {"address": {"type": "string"}},
                },
            ),
            types.Tool(
                name="list_profiles",
                description="List all available heating profiles.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="list_scenarios",
                description="List all saved scenarios (each scenario assigns a profile to specific devices).",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="apply_scenario",
                description="Apply a scenario: sets the assigned profile on each device in the scenario.",
                inputSchema={
                    "type": "object",
                    "required": ["scenario_id"],
                    "properties": {
                        "scenario_id": {"type": "integer", "description": "Scenario ID (from list_scenarios)"},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        result = await _dispatch(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    return server


async def _dispatch(name: str, args: dict) -> Any:
    cfg = config.get()
    adapter = cfg.get("bluetooth", {}).get("adapter")

    if name == "list_devices":
        devices = await db.list_devices()
        result = []
        for d in devices:
            status = await db.get_status(d["address"])
            result.append({**d, "status": status})
        return result

    elif name == "get_device_status":
        address = args["address"].upper()
        status = await db.get_status(address)
        if not status:
            # Try live poll
            device = await db.get_device(address)
            pin = device.get("pin") if device else None
            status = await poll_device(address, pin=pin, adapter=adapter)
        return status

    elif name == "set_temperature":
        address = args["address"].upper()
        device = await db.get_device(address)
        if not device:
            return {"error": f"Device {address} not configured"}
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=adapter) as dev:
            await dev.set_temperatures(
                comfort=args.get("comfort"),
                eco=args.get("eco"),
                manual=args.get("manual"),
            )
        return {"status": "ok", "address": address}

    elif name == "apply_profile":
        profile_name = args["profile_name"]
        devices_arg = args.get("devices", ["all"])
        if "all" in devices_arg:
            all_devs = await db.list_devices()
            addresses = [d["address"] for d in all_devs]
        else:
            addresses = [a.upper() for a in devices_arg]
        results = await prof.apply_profile(profile_name, addresses, apply_schedules=args.get("apply_schedules", True), adapter=adapter)
        return {"profile": profile_name, "results": results}

    elif name == "discover_devices":
        timeout = args.get("timeout", 10.0)
        found = await discovery.scan(timeout=timeout, adapter=adapter)
        return [{"address": d.address, "name": d.name, "rssi": d.rssi, "verified": d.verified} for d in found]

    elif name == "get_schedule":
        address = args["address"].upper()
        device = await db.get_device(address)
        if not device:
            return {"error": f"Device {address} not configured"}
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=adapter) as dev:
            schedules = await dev.get_all_day_schedules()
        result = {}
        for day_name, sched in schedules.items():
            result[day_name] = [
                {"start": p.start.strftime("%H:%M") if p.start else None,
                 "end": p.end.strftime("%H:%M") if p.end else None}
                for p in sched.periods
            ]
        return result

    elif name == "set_schedule":
        address = args["address"].upper()
        device = await db.get_device(address)
        if not device:
            return {"error": f"Device {address} not configured"}
        day_idx = day_name_to_index(args["day"])
        periods = []
        for p in args.get("periods", []):
            from datetime import time
            def _pt(s):
                if not s: return None
                h, m = s.split(":")
                return time(int(h), int(m))
            periods.append(TimePeriod(start=_pt(p.get("start")), end=_pt(p.get("end"))))
        while len(periods) < 4:
            periods.append(TimePeriod())
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=adapter) as dev:
            await dev.set_day_schedule(day_idx, DaySchedule(periods=periods[:4]))
        return {"status": "ok"}

    elif name == "get_holidays":
        address = args["address"].upper()
        device = await db.get_device(address)
        if not device:
            return {"error": f"Device {address} not configured"}
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=adapter) as dev:
            holidays = await dev.get_all_holidays()
        return [{"slot": h.slot, "active": h.active, "start": h.start, "end": h.end, "temperature": h.temperature} for h in holidays]

    elif name == "set_holiday":
        address = args["address"].upper()
        device = await db.get_device(address)
        if not device:
            return {"error": f"Device {address} not configured"}
        slot = args["slot"]
        holiday = Holiday(
            slot=slot,
            start=datetime.fromisoformat(args["start"]),
            end=datetime.fromisoformat(args["end"]),
            temperature=args["temperature"],
            active=True,
        )
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=adapter) as dev:
            await dev.set_holiday(slot, holiday)
        return {"status": "ok", "slot": slot}

    elif name == "get_history":
        address = args["address"].upper()
        rows = await db.get_history(address, limit=args.get("limit", 50))
        return {"address": address, "records": rows}

    elif name == "sync_time":
        address = args["address"].upper()
        device = await db.get_device(address)
        if not device:
            return {"error": f"Device {address} not configured"}
        async with CometBlueDevice(address, pin=device.get("pin"), adapter=adapter) as dev:
            await dev.sync_time()
        return {"status": "ok", "synced_at": datetime.now().isoformat()}

    elif name == "list_profiles":
        return [{"name": n} for n in prof.list_profiles()]

    elif name == "list_scenarios":
        return await db.list_presets()

    elif name == "apply_scenario":
        scenario_id = int(args["scenario_id"])
        preset = await db.get_preset(scenario_id)
        if not preset:
            return {"error": f"Scenario {scenario_id} not found"}
        results = {}
        for address, profile_name in preset["assignments"].items():
            if profile_name:
                try:
                    res = await prof.apply_profile(profile_name, [address], apply_schedules=True)
                    results[address] = res.get(address, "ok")
                except Exception as e:
                    results[address] = str(e)
        return {"scenario": preset["name"], "results": results}

    else:
        return {"error": f"Unknown tool: {name}"}


async def run():
    """Run the MCP server over stdio."""
    config.load()
    await db.init_db()
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_http(host: str = "0.0.0.0", port: int = 9090):
    """Run the MCP server over HTTP with SSE transport."""
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    config.load()

    mcp_server = create_server()
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_server.run(streams[0], streams[1], mcp_server.create_initialization_options())

    @asynccontextmanager
    async def lifespan(app):
        await db.init_db()
        yield

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    uv_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uv_server = uvicorn.Server(uv_config)
    log.info("MCP HTTP/SSE server starting on http://%s:%d/sse", host, port)
    await uv_server.serve()
