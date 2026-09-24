"""
Pydantic models for request validation and API response shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Requests ──────────────────────────────────────────────────────────────────


class RegisterDeviceRequest(BaseModel):
    """Payload for POST /devices."""

    id: str = Field(..., min_length=1, description="Unique device identifier")
    name: str = Field(..., min_length=1, description="Human-readable device name")


class HeartbeatRequest(BaseModel):
    """Payload for POST /devices/{id}/heartbeat."""

    timestamp: datetime = Field(
        ..., description="ISO-8601 timestamp reported by the device"
    )
    status: str = Field(..., min_length=1, description="Device-reported status, e.g. OK")
    # Optional extended fields (spec section 2)
    cpu_usage: Optional[int] = Field(
        None, ge=0, le=100, description="CPU usage percentage (0-100)"
    )
    signal_strength: Optional[int] = Field(
        None, description="Signal strength in dBm, e.g. -71"
    )


# ── Responses ─────────────────────────────────────────────────────────────────


class DeviceResponse(BaseModel):
    """A single device as returned by GET /devices and GET /devices/{id}."""

    id: str
    name: str
    status: str  # "ONLINE" | "OFFLINE"
    last_heartbeat: Optional[datetime] = None
    # Optional extended fields echoed back when present
    cpu_usage: Optional[int] = None
    signal_strength: Optional[int] = None


class SummaryResponse(BaseModel):
    """Fleet-wide summary returned by GET /summary."""

    total: int
    online: int
    offline: int
