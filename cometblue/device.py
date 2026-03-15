"""BLE device communication using bleak (cross-platform)."""

from __future__ import annotations

import asyncio
import logging
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

CONNECT_TIMEOUT = 45.0  # Pi 3B+ GATT service discovery can take 30+ seconds
OP_TIMEOUT = 10.0

# BlueZ only supports one BLE operation at a time — serialize all connections
_ble_lock = asyncio.Semaphore(1)


async def _reset_ble_adapter(address: Optional[str] = None):
    """Recover from a D-Bus EOFError after a failed BLE disconnect.

    On Linux/BlueZ with dbus-fast 4.x the D-Bus socket can close mid-operation,
    leaving BlueZ with a stale 'connected' entry for the device and bleak's
    BlueZManager dead.  This function:
      1. Forces a BlueZ-level disconnect via bluetoothctl (removes stale state)
      2. Clears bleak's per-loop BlueZManager cache (forces fresh D-Bus conn)
      3. Waits for BlueZ to stabilize before the next connection attempt
    """
    # Step 1: disconnect from BlueZ's side so the adapter is released
    if address:
        try:
            addr_clean = address.upper()
            proc = await asyncio.create_subprocess_exec(
                "bluetoothctl", "disconnect", addr_clean,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            log.info("bluetoothctl disconnect %s complete", addr_clean)
        except Exception as e:
            log.debug("bluetoothctl disconnect failed (non-fatal): %s", e)

    # Step 2: clear bleak's dead manager so next call creates a fresh one
    try:
        from bleak.backends.bluezdbus import manager as _bleak_mgr_mod
        loop = asyncio.get_running_loop()
        _bleak_mgr_mod._global_instances.pop(loop, None)
        log.info("BlueZManager cache cleared after EOFError")
    except Exception as e:
        log.warning("Could not clear BlueZManager cache: %s", e)

    # Step 3: give BlueZ time to re-initialize D-Bus connection
    await asyncio.sleep(5.0)


class CometBlueDevice:
    """Async context manager for communicating with a CometBlue thermostat."""

    def __init__(self, address: str, pin: Optional[int] = None, adapter: Optional[str] = None,
                 mac_address: Optional[str] = None):
        self.address = address
        self._original_address = address
        self.pin = pin
        self._adapter = adapter
        self._mac_address = mac_address
        self._client: Optional[BleakClient] = None

    async def __aenter__(self) -> "CometBlueDevice":
        await _ble_lock.acquire()
        try:
            kwargs = {"timeout": CONNECT_TIMEOUT}
            if self._adapter:
                kwargs["adapter"] = self._adapter
            try:
                self._client = BleakClient(self.address, **kwargs)
                # Use cached GATT services if BlueZ already knows the device.
                # On Pi 3B+, fresh service discovery takes ~30s which can exceed
                # the CometBlue device's unauthenticated-connection timeout.
                await self._client.connect(dangerous_use_bleak_cache=True)
            except BleakError as e:
                # Device not found + we have a stored MAC → try to resolve new UUID (e.g. after battery swap)
                if self._mac_address and "not found" in str(e).lower():
                    log.info(
                        "Device %s not found, attempting MAC-based rediscovery (MAC=%s)...",
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
            if self.pin is not None:
                await self._authenticate()
            return self
        except:
            _ble_lock.release()
            raise

    async def __aexit__(self, *args):
        try:
            if self._client and self._client.is_connected:
                await self._client.disconnect()
        except EOFError:
            # dbus-fast D-Bus socket closed unexpectedly (known issue on Pi 3B+
            # with bleak 2.x / dbus-fast 4.x). From BlueZ's perspective the
            # device may still appear connected. Reset the BLE subsystem so the
            # next connection attempt succeeds.
            log.warning("EOFError on BLE disconnect for %s — resetting BLE subsystem", self.address)
            await _reset_ble_adapter(self.address)
        finally:
            _ble_lock.release()

    async def _authenticate(self):
        data = encode_pin(self.pin)
        # Try Write With Response first; some devices only support Write Without Response
        try:
            await self._client.write_gatt_char(UUID_PIN, data, response=True)
        except Exception:
            await self._client.write_gatt_char(UUID_PIN, data, response=False)
        log.debug("PIN authentication sent for %s", self.address)

    async def _read(self, uuid: str) -> bytes:
        return await asyncio.wait_for(
            self._client.read_gatt_char(uuid), timeout=OP_TIMEOUT
        )

    async def _write(self, uuid: str, data: bytes):
        await asyncio.wait_for(
            self._client.write_gatt_char(uuid, data, response=True),
            timeout=OP_TIMEOUT,
        )

    # ── Read operations ───────────────────────────────────────────────────────

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
        """Try to read the BLE System ID characteristic and decode the MAC address.
        System ID is 8 bytes: bytes[0-2] = lower MAC (reversed), [3-4] = 0xFF 0xFE, [5-7] = upper MAC (reversed).
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

    # ── Write operations ──────────────────────────────────────────────────────

    async def set_temperatures(
        self,
        comfort: Optional[float] = None,
        eco: Optional[float] = None,
        offset: float = 0.0,
        window_open: Optional[bool] = None,
        window_minutes: Optional[int] = None,
    ):
        data = encode_temperatures(
            comfort=comfort,
            eco=eco,
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
        """
        Verify a PIN against the device.
        Writes the PIN (with response=True fallback to response=False, same as _authenticate),
        then tries to read a PIN-protected characteristic (day schedule).
        Returns True if the PIN is accepted, False if rejected.
        """
        try:
            data = encode_pin(pin)
            try:
                await self._client.write_gatt_char(UUID_PIN, data, response=True)
            except Exception:
                await self._client.write_gatt_char(UUID_PIN, data, response=False)
            # Day schedule read requires valid PIN — use it as the probe
            await self._read(get_day_uuid(1))
            return True
        except Exception as e:
            log.debug("PIN test failed for %s: %s", self.address, e)
            return False

    # ── Convenience: full status poll ─────────────────────────────────────────

    async def poll_status(self) -> dict:
        """Read all commonly needed values in one connection."""
        result = {"address": self.address}

        # If auto-resolve changed the address, record both so the caller can update DB
        if self.address != self._original_address:
            result["new_address"] = self.address
            result["old_address"] = self._original_address

        # Temperature read is essential — let errors (incl. auth failures) propagate
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

        # Battery, datetime, flags — optional, swallow errors
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

        # Read real MAC via System ID (works because we're authenticated)
        try:
            mac = await self.get_mac_from_system_id()
            if mac:
                result["mac_address"] = mac
                log.debug("MAC read from System ID for %s: %s", self.address, mac)
        except Exception as e:
            log.debug("Could not read System ID MAC from %s: %s", self.address, e)

        return result


_AUTH_KEYWORDS = (
    "insufficient authentication",
    "insufficient authorization",
    "insufficient encryption",
    "permission denied",
    "not permitted",
    "att error: 0x0",
    "att error: 0x1",
)


async def poll_device(address: str, pin: Optional[int] = None, adapter: Optional[str] = None,
                      mac_address: Optional[str] = None) -> dict:
    """Standalone helper: connect, poll, disconnect."""
    # Note: no pre-scan for RSSI here — on Linux/BlueZ running a BleakScanner
    # scan immediately before connecting corrupts adapter state and causes
    # TimeoutError on the connection. RSSI is updated via the discovery endpoint.
    try:
        async with CometBlueDevice(address, pin=pin, adapter=adapter, mac_address=mac_address) as dev:
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
