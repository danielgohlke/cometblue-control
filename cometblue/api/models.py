"""Pydantic models for the REST API."""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from pydantic import BaseModel, Field


class DeviceAdd(BaseModel):
    address: str
    name: str = ""
    pin: Optional[int] = None
    adapter: Optional[str] = None


class DeviceOut(BaseModel):
    address: str
    name: str
    pin: Optional[int] = None
    adapter: Optional[str] = None
    mac_address: Optional[str] = None
    active: bool = True
    added_at: str
    last_seen: Optional[str] = None
    rssi: Optional[int] = None


class TemperaturesSet(BaseModel):
    comfort: Optional[float] = Field(None, ge=5.0, le=35.0)
    eco: Optional[float] = Field(None, ge=5.0, le=35.0)
    offset: Optional[float] = Field(None, ge=-3.5, le=3.5)
    window_open: Optional[bool] = None
    window_minutes: Optional[int] = Field(None, ge=0, le=60)


class TimePeriodOut(BaseModel):
    start: Optional[str] = None   # "HH:MM" or null
    end: Optional[str] = None


class DayScheduleOut(BaseModel):
    day: str
    periods: list[TimePeriodOut]


class TimePeriodIn(BaseModel):
    start: Optional[str] = None   # "HH:MM" or null
    end: Optional[str] = None


class DayScheduleSet(BaseModel):
    periods: list[TimePeriodIn] = Field(max_length=4)


class HolidayOut(BaseModel):
    slot: int
    active: bool
    start: Optional[str] = None
    end: Optional[str] = None
    temperature: Optional[float] = None


class HolidaySet(BaseModel):
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    temperature: Optional[float] = Field(None, ge=5.0, le=35.0)
    active: bool = True


class ProfileOut(BaseModel):
    name: str
    comfort_temp: Optional[float] = None
    eco_temp: Optional[float] = None
    manual_temp: Optional[float] = None
    schedules: Optional[dict] = None


class ProfileApply(BaseModel):
    devices: list[str] = ["all"]
    apply_schedules: bool = True


class FlagsSet(BaseModel):
    child_lock: Optional[bool] = None


class DiscoverResult(BaseModel):
    address: str
    name: str
    rssi: Optional[int] = None
    verified: bool = False
