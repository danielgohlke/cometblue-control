"""BLE device communication using bleak (cross-platform).

Platform strategies
-------------------
macOS (CoreBluetooth):
  - Devices are addressed by CoreBluetooth-assigned UUIDs, not MAC addresses
  - The ``adapter`` parameter is not supported by CoreBluetooth and is omitted
  - ``dangerous_use_bleak_cache`` is omitted (CoreBluetooth handles caching
    internally and the flag can cause connection failures on macOS)
  - No BlueZ/D-Bus → no EOFError on disconnect, no ``bluetoothctl`` cleanup
  - Connect timeout is shorter (~15 s) since GATT discovery is faster

Linux / Raspberry Pi (BlueZ via dbus-fast):
  - Devices are addressed by MAC address
  - ``adapter`` is respected (e.g. ``hci0``)
  - ``dangerous_use_bleak_cache=True`` is set — on Pi 3B+ fresh GATT service
    discovery takes ~30 s which can trigger CometBlue's unauthenticated-
    connection timeout; the cache skips that round-trip on subsequent polls
  - dbus-fast can raise ``EOFError`` on disconnect (D-Bus socket closed mid-op);
    recovery is done via ``bluetoothctl disconnect`` + BlueZManager cache clear
  - A process-wide asyncio.Semaphore(1) serialises all BLE operations because
    BlueZ only supports one active GATT connection reliably
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

from bleak import BleakClient, BleakError, BleakScanner

from .protocol import (
    UUID_TEMPERATURES, UUID_BATTERY, UUID_DATETIME, UUID_FLAGS,
    UUID_FIRMWARE2, UUID_LCD_TIMER, UUID_PIN,
    UUID_DEVICE_NAME, UUID_SYSTEM_ID, UUID_MODEL_NUMBER, UUID_FIRMWARE_REVISION,
    UUID_SOFTWARE_REVISION, UUID_MANUFACTURER_NAME,
    Temperatures, DaySchedule, Holiday, Flags,
    decode_temperatures, encode_temperatures,
    decode_datetime, encode_datetime,
    decode_day_schedule, encode_day_schedule,
    decode_holiday, encode_holiday, encode_holiday_clear,
    decode_flags,
    encode_pin,
    get_day_uuid, get_holiday_uuid,
    DAY_NAMES,
)

log = logging.getLogger(__name__)

IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Timeouts differ by platform:
#   macOS — CoreBluetooth service discovery is fast (~5 s)
#   Linux — BlueZ service discovery is slower; Pi 3B+ can take 30+ s
CONNECT_TIMEOUT = 15.0 if IS_MACOS else 45.0
OP_TIMEOUT = 10.0

# BlueZ only supports one BLE operation at a time — serialize all connections.
# On macOS CoreBluetooth can handle more, but CometBlue devices accept only one
# concurrent connection anyway so the semaphore is harmless and prevents races.
_ble_lock = asyncio.Semaphore(1)


# ── Linux-only BLE recovery ────────────────────────────────────────────────────

async def _reset_ble_adapter_linux(address: Optional[str] = None):
    """Recover from a D-Bus EOFError after a failed BLE disconnect (Linux only).

    On Linux/BlueZ with dbus-fast 4.x the D-Bus socket can close mid-operation,
    leaving BlueZ with a stale 'connected' entry and bleak's BlueZManager dead.
    Steps:
      1. Force a BlueZ-level disconnect via bluetoothctl (clears stale state)
      2. Clear bleak's per-loop BlueZManager cache (forces fresh D-Bus connection)
      3. Wait for BlueZ to stabilise before the next connection attempt
    """
    if address:
        try:
            proc = await asyncio.create_subprocess_exec(
                "bluetoothctl", "disconnect", address.upper(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            log.info("bluetoothctl disconnect %s complete", address.upper())
        except Exception as e:
            log.debug("bluetoothctl disconnect failed (non-fatal): %s", e)

    try:
        from bleak.backends.bluezdbus import manager as _bleak_mgr_mod
        loop = asyncio.get_running_loop()
        _bleak_mgr_mod._global_instances.pop(loop, None)
        log.info("BlueZManager cache cleared after EOFError")
    except Exception as e:
        log.warning("Could not clear BlueZManager cache: %s", e)

    await asyncio.sleep(5.0)


# ── Device class ──────────────────────────────────────────────────────────────

class CometBlueDevice:
    """Async context manager for communicating with a CometBlue thermostat."""

    def __init__(self, address: str, pin: Optional[int] = None,
                 adapter: Optional[str] = None, mac_address: Optional[str] = None):
        self.address = address
        self._original_address = address
        self.pin = pin
        self._adapter = adapter          # ignored on macOS
        self._mac_address = mac_address  # real hardware MAC for UUID re-resolution
        self._client: Optional[BleakClient] = None

    # ── Context manager ────────────────────────────────────────────────────────

    async def __aenter__(self) -> "CometBlueDevice":
        await _ble_lock.acquire()
        try:
            if IS_MACOS:
                await self._connect_macos()
            else:
                await self._connect_linux()
            if self.pin is not None:
                await self._authenticate()
            return self
        except Exception:
            _ble_lock.release()
            raise

    async def __aexit__(self, *args):
        try:
            if self._client and self._client.is_connected:
                await self._client.disconnect()
        except EOFError:
            # dbus-fast D-Bus socket closed unexpectedly — Linux/Pi only.
            # From BlueZ's perspective the device may still appear connected.
            log.warning("EOFError on disconnect for %s — resetting BLE subsystem", self.address)
            if IS_LINUX:
                await _reset_ble_adapter_linux(self.address)
        except Exception as e:
            # macOS CoreBluetooth can raise on disconnect when the device
            # drops the link itself (e.g. unauthenticated timeout). Not fatal.
            log.debug("Error on BLE disconnect for %s (non-fatal): %s", self.address, e)
        finally:
            _ble_lock.release()

    # ── Platform-specific connect strategies ──────────────────────────────────

    async def _connect_macos(self):
        """CoreBluetooth (macOS) connection strategy.

        Key differences from Linux:
        - No ``adapter`` kwarg — CoreBluetooth manages the adapter transparently
        - No ``dangerous_use_bleak_cache`` — CoreBluetooth caches services itself;
          the flag can cause connection failures or stale GATT tables on macOS
        - Shorter timeout (service discovery is ~5 s vs 30+ s on Pi 3B+)
        - Address re-resolution uses the same UUID-scan path (no MAC addresses
          are visible at the OS level on macOS)
        """
        kwargs = {"timeout": CONNECT_TIMEOUT}
        try:
            self._client = BleakClient(self.address, **kwargs)
            await self._client.connect()
        except BleakError as e:
            if self._mac_address and "not found" in str(e).lower():
                log.info(
                    "Device %s not found on macOS, attempting MAC-based rediscovery (MAC=%s)…",
                    self.address, self._mac_address,
                )
                from .discovery import find_by_mac
                found = await find_by_mac(self._mac_address, pin=self.pin)
                if found:
                    log.info(
                        "Resolved UUID via MAC %s: %s → %s",
                        self._mac_address, self.address, found.address,
                    )
                    self.address = found.address
                    self._client = BleakClient(self.address, **kwargs)
                    await self._client.connect()
                else:
                    raise
            else:
                raise

    async def _connect_linux(self):
        """BlueZ (Linux / Raspberry Pi) connection strategy.

        Key differences from macOS:
        - ``adapter`` is passed when configured (allows selecting ``hci0`` etc.)
        - ``dangerous_use_bleak_cache=True`` is set to skip GATT service
          discovery on subsequent connects — essential on Pi 3B+ where fresh
          discovery takes ~30 s and can trigger CometBlue's auth timeout
        - Longer timeout (45 s) to handle slow Pi GATT discovery on first connect
        - Address re-resolution passes ``adapter`` through to the scanner
        """
        kwargs = {"timeout": CONNECT_TIMEOUT}
        if self._adapter:
            kwargs["adapter"] = self._adapter
        try:
            self._client = BleakClient(self.address, **kwargs)
            await self._client.connect(dangerous_use_bleak_cache=True)
        except BleakError as e:
            if self._mac_address and "not found" in str(e).lower():
                log.info(
                    "Device %s not found on Linux, attempting MAC-based rediscovery (MAC=%s)…",
                    self.address, self._mac_address,
                )
                from .discovery import find_by_mac
                found = await find_by_mac(self._mac_address, pin=self.pin, adapter=self._adapter)
                if found:
                    log.info(
                        "Resolved address via MAC %s: %s → %s",
                        self._mac_address, self.address, found.address,
                    )
                    self.address = found.address
                    self._client = BleakClient(self.address, **kwargs)
                    await self._client.connect(dangerous_use_bleak_cache=True)
                else:
                    raise
            else:
                raise

    # ── Authentication ─────────────────────────────────────────────────────────

    async def _authenticate(self):
        data = encode_pin(self.pin)
        # Try Write With Response first; some firmware only supports Without Response
        try:
            await self._client.write_gatt_char(UUID_PIN, data, response=True)
        except Exception:
            await self._client.write_gatt_char(UUID_PIN, data, response=False)
        log.debug("PIN authentication sent for %s", self.address)

    # ── Low-level I/O ──────────────────────────────────────────────────────────

    async def _read(self, uuid: str) -> bytes:
        return await asyncio.wait_for(
            self._client.read_gatt_char(uuid), timeout=OP_TIMEOUT
        )

    async def _write(self, uuid: str, data: bytes):
        await asyncio.wait_for(
            self._client.write_gatt_char(uuid, data, response=True),
            timeout=OP_TIMEOUT,
        )

    # ── Read operations ────────────────────────────────────────────────────────

    async def get_temperatures(self) -> Temperatures:
        data = await self._read(UUID_TEMPERATURES)
        return decode_temperatures(data)

    async def get_battery(self) -> Optional[int]:
        data = await self._read(UUID_BATTERY)
        val = data[0]
        return None if val == 255 else val

    async def get_datetime(self):
        data = await self._read(UUID_DATETIME)
        return decode_datetime(data)

    async def get_day_schedule(self, day: int) -> DaySchedule:
        """day: 1=Monday … 7=Sunday"""
        data = await self._read(get_day_uuid(day))
        return decode_day_schedule(data)

    async def get_all_day_schedules(self) -> dict[str, DaySchedule]:
        result = {}
        for i, name in enumerate(DAY_NAMES, start=1):
            try:
                result[name] = await self.get_day_schedule(i)
            except Exception as e:
                log.warning("Failed to read schedule for %s: %s", name, e)
        return result

    async def get_holiday(self, slot: int) -> Holiday:
        """slot: 1–8"""
        data = await self._read(get_holiday_uuid(slot))
        h = decode_holiday(data)
        h.slot = slot
        return h

    async def get_all_holidays(self) -> list[Holiday]:
        result = []
        for slot in range(1, 9):
            try:
                h = await self.get_holiday(slot)
                result.append(h)
            except Exception as e:
                log.warning("Failed to read holiday slot %d: %s", slot, e)
        return result

    async def get_flags(self) -> Flags:
        data = await self._read(UUID_FLAGS)
        return decode_flags(data)

    async def set_child_lock(self, enabled: bool):
        """Read FLAGS, flip child_lock bit (byte 0 bit 7 = 0x80), write back."""
        data = await self._read(UUID_FLAGS)
        b = bytearray(data)
        if len(b) >= 1:
            if enabled:
                b[0] |= 0x80
            else:
                b[0] &= ~0x80 & 0xFF
        await self._write(UUID_FLAGS, bytes(b))

    async def get_mac_from_system_id(self) -> Optional[str]:
        """Read the BLE System ID characteristic and decode the MAC address.

        System ID is 8 bytes:
          bytes[0-2] = lower MAC (reversed)
          bytes[3-4] = 0xFF 0xFE (OUI separator)
          bytes[5-7] = upper MAC (reversed)
        Returns 'AA:BB:CC:DD:EE:FF' or None if unavailable.
        """
        try:
            data = await self._read(UUID_SYSTEM_ID)
            if len(data) == 8 and data[3] == 0xFF and data[4] == 0xFE:
                mac = f"{data[7]:02X}:{data[6]:02X}:{data[5]:02X}:{data[2]:02X}:{data[1]:02X}:{data[0]:02X}"
                return mac
        except Exception:
            pass
        return None

    async def get_device_info(self) -> dict:
        info = {}
        for key, uuid in [
            ("device_name", UUID_DEVICE_NAME),
            ("model_number", UUID_MODEL_NUMBER),
            ("firmware_revision", UUID_FIRMWARE_REVISION),
            ("software_revision", UUID_SOFTWARE_REVISION),
            ("manufacturer_name", UUID_MANUFACTURER_NAME),
        ]:
            try:
                data = await self._read(uuid)
                info[key] = data.decode("utf-8", errors="replace").strip()
            except Exception:
                info[key] = None
        return info

    # ── Write operations ───────────────────────────────────────────────────────

    async def set_temperatures(
        self,
        comfort: Optional[float] = None,
        eco: Optional[float] = None,
        manual: Optional[float] = None,
        offset: float = 0.0,
        window_open: Optional[bool] = None,
        window_minutes: Optional[int] = None,
    ):
        data = encode_temperatures(
            comfort=comfort,
            eco=eco,
            manual=manual,
            offset=offset,
            window_open=window_open,
            window_minutes=window_minutes,
        )
        await self._write(UUID_TEMPERATURES, data)

    async def set_day_schedule(self, day: int, schedule: DaySchedule):
        data = encode_day_schedule(schedule)
        await self._write(get_day_uuid(day), data)

    async def set_holiday(self, slot: int, holiday: Holiday):
        if not holiday.active or not holiday.start or not holiday.end or holiday.temperature is None:
            data = encode_holiday_clear()
        else:
            data = encode_holiday(holiday.start, holiday.end, holiday.temperature)
        await self._write(get_holiday_uuid(slot), data)

    async def clear_holiday(self, slot: int):
        await self._write(get_holiday_uuid(slot), encode_holiday_clear())

    async def sync_time(self, dt=None):
        data = encode_datetime(dt)
        await self._write(UUID_DATETIME, data)

    async def change_pin(self, new_pin: int):
        await self._write(UUID_PIN, encode_pin(new_pin))

    async def test_pin(self, pin: int) -> bool:
        """Verify a PIN against the device.

        Writes the PIN then reads a PIN-protected characteristic (day schedule)
        as a probe. Returns True if accepted, False if rejected.
        """
        try:
            data = encode_pin(pin)
            try:
                await self._client.write_gatt_char(UUID_PIN, data, response=True)
            except Exception:
                await self._client.write_gatt_char(UUID_PIN, data, response=False)
            await self._read(get_day_uuid(1))
            return True
        except Exception as e:
            log.debug("PIN test failed for %s: %s", self.address, e)
            return False

    # ── Convenience: full status poll ─────────────────────────────────────────

    async def poll_status(self) -> dict:
        """Read all commonly needed values in one connection."""
        result = {"address": self.address}

        if self.address != self._original_address:
            result["new_address"] = self.address
            result["old_address"] = self._original_address

        temps = await self.get_temperatures()
        result["temperatures"] = {
            "current": temps.current,
            "manual": temps.manual,
            "comfort": temps.comfort,
            "eco": temps.eco,
            "offset": temps.offset,
            "window_open": temps.window_open,
            "window_minutes": temps.window_minutes,
        }

        try:
            result["battery"] = await self.get_battery()
        except Exception as e:
            log.warning("Failed to read battery from %s: %s", self.address, e)
            result["battery"] = None

        try:
            dt = await self.get_datetime()
            result["device_time"] = dt.isoformat()
        except Exception as e:
            log.warning("Failed to read datetime from %s: %s", self.address, e)
            result["device_time"] = None

        try:
            flags = await self.get_flags()
            result["flags"] = {
                "child_lock": flags.child_lock,
                "manual_mode": flags.manual_mode,
                "dst_active": flags.dst_active,
                "antifrost": flags.antifrost,
                "raw": flags.raw.hex(),
            }
        except Exception as e:
            log.warning("Failed to read flags from %s: %s", self.address, e)
            result["flags"] = None

        try:
            mac = await self.get_mac_from_system_id()
            if mac:
                result["mac_address"] = mac
                log.debug("MAC read from System ID for %s: %s", self.address, mac)
        except Exception as e:
            log.debug("Could not read System ID MAC from %s: %s", self.address, e)

        return result


# ── Auth error detection ───────────────────────────────────────────────────────

_AUTH_KEYWORDS = (
    "insufficient authentication",
    "insufficient authorization",
    "insufficient encryption",
    "permission denied",
    "not permitted",
    "att error: 0x0",
    "att error: 0x1",
)


async def poll_device(address: str, pin: Optional[int] = None,
                      adapter: Optional[str] = None,
                      mac_address: Optional[str] = None) -> dict:
    """Standalone helper: connect, poll status, disconnect."""
    # Note: on Linux/BlueZ, running BleakScanner immediately before connecting
    # corrupts adapter state and causes TimeoutError. RSSI is updated separately
    # via the discovery endpoint, not during polling.
    try:
        async with CometBlueDevice(address, pin=pin, adapter=adapter,
                                   mac_address=mac_address) as dev:
            return await dev.poll_status()
    except BleakError as e:
        err_str = str(e) or type(e).__name__
        is_auth = any(kw in err_str.lower() for kw in _AUTH_KEYWORDS)
        if is_auth:
            log.error("Auth error (wrong PIN?) polling %s: %s", address, err_str)
            return {"address": address, "error": f"auth_failed: {err_str}"}
        log.error("BLE error polling %s: %s", address, err_str)
        return {"address": address, "error": err_str}
    except Exception as e:
        err_str = str(e) or type(e).__name__
        log.error("Unexpected error polling %s: %s", address, err_str)
        return {"address": address, "error": err_str}
