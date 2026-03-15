"""BLE device discovery — finds CometBlue thermostats."""

from __future__ import annotations

import asyncio
import logging
from asyncio import Queue
from dataclasses import dataclass
from typing import AsyncGenerator, Optional, Tuple

from bleak import BleakScanner, BleakClient, BleakError

from .protocol import (
    UUID_MANUFACTURER_NAME, UUID_MODEL_NUMBER, UUID_SYSTEM_ID, UUID_PIN,
    SUPPORTED_MANUFACTURER, SUPPORTED_MODEL,
    encode_pin,
)

log = logging.getLogger(__name__)

SCAN_TIMEOUT = 10.0
VERIFY_TIMEOUT = 8.0


@dataclass
class DiscoveredDevice:
    address: str
    name: str
    rssi: Optional[int] = None
    verified: bool = False  # True = confirmed manufacturer+model via GATT
    mac_address: Optional[str] = None  # Real MAC from BLE System ID characteristic


async def scan(timeout: float = SCAN_TIMEOUT, adapter: Optional[str] = None) -> list[DiscoveredDevice]:
    """
    Scan for BLE devices and return those that look like CometBlue thermostats.

    First pass: name-based filter ("Comet Blue").
    Second pass: GATT verification of manufacturer + model (best-effort).
    """
    log.info("Starting BLE scan (%.1fs)...", timeout)

    kwargs = {"timeout": timeout}
    if adapter:
        kwargs["adapter"] = adapter

    devices = await BleakScanner.discover(**kwargs)

    candidates = []
    for d in devices:
        name = (d.name or "").strip()
        if "comet" in name.lower() or "blue" in name.lower():
            candidates.append(DiscoveredDevice(
                address=d.address,
                name=name,
                rssi=getattr(d, "rssi", None),
            ))
            log.debug("Candidate: %s (%s)", name, d.address)

    log.info("Found %d candidate(s), verifying via GATT...", len(candidates))

    # Verify each candidate (also reads MAC via System ID)
    verified = []
    for candidate in candidates:
        ok, mac = await _verify_device(candidate.address, adapter)
        candidate.verified = ok
        candidate.mac_address = mac
        if ok or candidate.name.lower() == "comet blue":
            verified.append(candidate)

    log.info("Discovery complete: %d CometBlue device(s) found", len(verified))
    return verified


async def scan_streaming(
    timeout: float = SCAN_TIMEOUT,
    adapter: Optional[str] = None,
) -> AsyncGenerator[Tuple[str, object], None]:
    """
    Async generator that yields events during a BLE scan:
      ("device",   DiscoveredDevice)  — candidate found
      ("progress", float)             — elapsed seconds (every ~0.5 s)
      ("done",     None)              — scan finished
    """
    queue: Queue = Queue()
    found: set[str] = set()

    def _on_device(device, adv_data):
        name = (device.name or "").strip()
        if device.address not in found and (
            "comet" in name.lower() or "blue" in name.lower()
        ):
            found.add(device.address)
            rssi = getattr(adv_data, "rssi", None) or getattr(device, "rssi", None)
            queue.put_nowait(DiscoveredDevice(address=device.address, name=name, rssi=rssi))
            log.debug("Streaming candidate: %s (%s)", name, device.address)

    kwargs: dict = {}
    if adapter:
        kwargs["adapter"] = adapter

    scanner = BleakScanner(detection_callback=_on_device, **kwargs)
    await scanner.start()
    log.info("Streaming BLE scan started (%.1fs)", timeout)

    tick = 0.5
    elapsed = 0.0
    try:
        while elapsed < timeout:
            await asyncio.sleep(tick)
            elapsed = min(elapsed + tick, timeout)
            yield ("progress", elapsed)
            while not queue.empty():
                yield ("device", queue.get_nowait())
    finally:
        await scanner.stop()

    # Drain any last-moment discoveries
    while not queue.empty():
        yield ("device", queue.get_nowait())

    yield ("done", None)
    log.info("Streaming scan done: %d candidate(s)", len(found))

    # Post-scan MAC verification — runs after "done" so the UI isn't blocked
    for addr in list(found):
        _, mac = await _verify_device(addr, adapter)
        if mac:
            yield ("mac", DiscoveredDevice(address=addr, name="", mac_address=mac))


async def find_by_mac(mac: str, timeout: float = SCAN_TIMEOUT,
                      adapter: Optional[str] = None,
                      pin: Optional[int] = None) -> Optional[DiscoveredDevice]:
    """Scan for a CometBlue device with the given MAC address (from System ID).
    Authenticates with PIN before reading System ID (required on CometBlue).
    Returns a DiscoveredDevice with the current BLE address (UUID on macOS) if found.
    """
    mac_upper = mac.upper()
    log.info("Scanning for device with MAC %s (pin=%s)...", mac_upper, "yes" if pin is not None else "no")

    kwargs = {"timeout": timeout}
    if adapter:
        kwargs["adapter"] = adapter

    devices = await BleakScanner.discover(**kwargs)
    for d in devices:
        name = (d.name or "").strip()
        if "comet" not in name.lower() and "blue" not in name.lower():
            continue
        # Connect, optionally authenticate, then check System ID
        try:
            ckwargs = {"timeout": VERIFY_TIMEOUT}
            if adapter:
                ckwargs["adapter"] = adapter
            async with BleakClient(d.address, **ckwargs) as client:
                if pin is not None:
                    pin_data = encode_pin(pin)
                    try:
                        await client.write_gatt_char(UUID_PIN, pin_data, response=True)
                    except Exception:
                        await client.write_gatt_char(UUID_PIN, pin_data, response=False)
                data = await client.read_gatt_char(UUID_SYSTEM_ID)
                log.info("find_by_mac: System ID raw for %s: %s", d.address, data.hex())
                if len(data) == 8 and data[3] == 0xFF and data[4] == 0xFE:
                    found_mac = f"{data[7]:02X}:{data[6]:02X}:{data[5]:02X}:{data[2]:02X}:{data[1]:02X}:{data[0]:02X}"
                    if found_mac.upper() == mac_upper:
                        log.info("Found device with MAC %s at address %s", mac_upper, d.address)
                        return DiscoveredDevice(
                            address=d.address,
                            name=name,
                            rssi=getattr(d, "rssi", None),
                            verified=True,
                            mac_address=found_mac,
                        )
        except Exception as e:
            log.debug("Could not check System ID of %s: %s", d.address, e)
    return None


async def _verify_device(address: str, adapter: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Connect to a device, check manufacturer + model, and read MAC via System ID.
    Returns (verified, mac_address).
    """
    try:
        kwargs = {"timeout": VERIFY_TIMEOUT}
        if adapter:
            kwargs["adapter"] = adapter
        async with BleakClient(address, **kwargs) as client:
            manufacturer = ""
            model = ""
            mac: Optional[str] = None

            try:
                data = await client.read_gatt_char(UUID_MANUFACTURER_NAME)
                manufacturer = data.decode("utf-8", errors="replace").strip().lower()
            except Exception:
                pass
            try:
                data = await client.read_gatt_char(UUID_MODEL_NUMBER)
                model = data.decode("utf-8", errors="replace").strip().lower()
            except Exception:
                pass
            try:
                data = await client.read_gatt_char(UUID_SYSTEM_ID)
                log.info("System ID raw for %s: %s (len=%d)", address, data.hex(), len(data))
                if len(data) == 8:
                    if data[3] == 0xFF and data[4] == 0xFE:
                        mac = f"{data[7]:02X}:{data[6]:02X}:{data[5]:02X}:{data[2]:02X}:{data[1]:02X}:{data[0]:02X}"
                        log.info("MAC decoded (standard OUI format): %s", mac)
                    else:
                        # Try alternative: straight reversed byte order
                        mac_alt = f"{data[5]:02X}:{data[4]:02X}:{data[3]:02X}:{data[2]:02X}:{data[1]:02X}:{data[0]:02X}"
                        log.info("System ID bytes[3:5]=%02X %02X (not FF FE) — alt MAC attempt: %s",
                                 data[3], data[4], mac_alt)
            except Exception as e:
                log.info("System ID read failed for %s: %s", address, e)

            ok = SUPPORTED_MANUFACTURER in manufacturer and SUPPORTED_MODEL in model
            log.info("Verify %s: manufacturer=%r model=%r mac=%r → %s", address, manufacturer, model, mac, ok)
            return ok, mac
    except (BleakError, asyncio.TimeoutError) as e:
        log.debug("Could not verify %s: %s", address, e)
        return False, None
