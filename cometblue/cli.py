"""Command-line interface."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click
import uvicorn

from . import config


@click.group()
@click.option("--config-file", "-c", type=click.Path(), default=None, help="Config file path")
@click.option("--log-level", "-l", default=None, help="Log level (DEBUG, INFO, WARNING, ERROR)")
def cli(config_file, log_level):
    """CometBlue Control — manage CometBlue BLE thermostats."""
    cfg = config.load(Path(config_file) if config_file else None)
    level = log_level or cfg.get("log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@cli.command()
@click.option("--host", default=None, help="Bind host (default: from config)")
@click.option("--port", "-p", default=None, type=int, help="Port (default: from config)")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev mode)")
def serve(host, port, reload):
    """Start the REST API server (+ Web UI if enabled)."""
    cfg = config.get()
    _host = host or cfg.get("host", "0.0.0.0")
    _port = port or cfg.get("port", 8080)

    click.echo(f"Starting CometBlue Control on http://{_host}:{_port}")
    click.echo(f"API docs: http://{_host}:{_port}/docs")

    uvicorn.run(
        "cometblue.api.app:create_app",
        factory=True,
        host=_host,
        port=_port,
        reload=reload,
        log_level=cfg.get("log_level", "info").lower(),
    )


@cli.command()
def mcp():
    """Start the MCP server (stdio transport for Claude integration)."""
    try:
        from .mcp.server import run
    except ImportError:
        click.echo("MCP SDK not installed. Run: pip install 'cometblue-control[mcp]'", err=True)
        sys.exit(1)
    asyncio.run(run())


@cli.command()
@click.option("--timeout", "-t", default=10.0, show_default=True, help="Scan duration (seconds)")
@click.option("--json", "as_json", is_flag=True, default=False)
def discover(timeout, as_json):
    """Scan for CometBlue devices via Bluetooth."""
    from . import discovery

    async def _scan():
        return await discovery.scan(timeout=timeout)

    click.echo(f"Scanning for CometBlue devices ({timeout}s)...")
    found = asyncio.run(_scan())

    if as_json:
        click.echo(json.dumps([
            {"address": d.address, "name": d.name, "rssi": d.rssi, "verified": d.verified}
            for d in found
        ], indent=2))
    else:
        if not found:
            click.echo("No devices found.")
        for d in found:
            verified = " ✓" if d.verified else ""
            rssi = f" (RSSI: {d.rssi})" if d.rssi else ""
            click.echo(f"  {d.address}  {d.name}{rssi}{verified}")


@cli.command()
@click.argument("address")
@click.option("--pin", default=None, type=int)
@click.option("--json", "as_json", is_flag=True, default=False)
def status(address, pin, as_json):
    """Poll a device and show its current status."""
    from .device import poll_device

    async def _poll():
        return await poll_device(address, pin=pin)

    result = asyncio.run(_poll())
    if as_json:
        click.echo(json.dumps(result, indent=2, default=str))
    else:
        temps = result.get("temperatures") or {}
        click.echo(f"Device: {result['address']}")
        if result.get("error"):
            click.echo(f"  Error: {result['error']}")
        else:
            click.echo(f"  Current temp:  {temps.get('current')} °C")
            click.echo(f"  Manual target: {temps.get('manual')} °C")
            click.echo(f"  Comfort:       {temps.get('comfort')} °C")
            click.echo(f"  Eco:           {temps.get('eco')} °C")
            click.echo(f"  Battery:       {result.get('battery')} %")
            click.echo(f"  Device time:   {result.get('device_time')}")


@cli.command("test-pin")
@click.argument("address")
@click.option("--pin", required=True, type=int, help="PIN to test")
def test_pin(address, pin):
    """Test whether a PIN is accepted by the device."""
    from .device import CometBlueDevice

    async def _test():
        async with CometBlueDevice(address) as dev:
            return await dev.test_pin(pin)

    click.echo(f"Testing PIN {pin} on {address}...")
    try:
        valid = asyncio.run(_test())
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if valid:
        click.echo("PIN is correct.")
    else:
        click.echo("PIN is incorrect.")
        sys.exit(1)


@cli.command("list-profiles")
def list_profiles():
    """List available heating profiles."""
    from . import profiles as prof
    names = prof.list_profiles()
    if not names:
        click.echo("No profiles found.")
    for name in names:
        click.echo(f"  {name}")
