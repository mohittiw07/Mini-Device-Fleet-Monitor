"""
Thread-safe in-memory device store.

Design decisions:
- Status (ONLINE/OFFLINE) is computed dynamically on every read by comparing
  the server-recorded receive time against the configurable timeout. Nothing
  is stored as "ONLINE" or "OFFLINE" — stale data is impossible.
- A threading.Lock protects all mutations so the store is safe when uvicorn
  runs sync route handlers in its thread-pool executor.
- The clock is injected via `now_fn` so tests can control time without
  sleeping or monkey-patching builtins.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default timeout from the spec: 30 seconds
OFFLINE_TIMEOUT_SECONDS: int = 30


# ── Custom exceptions ─────────────────────────────────────────────────────────


class DeviceNotFoundError(Exception):
    """Raised when an operation targets a device ID that does not exist."""


class DeviceAlreadyExistsError(Exception):
    """Raised when trying to register a device ID that is already registered."""


# ── Store ─────────────────────────────────────────────────────────────────────


class DeviceStore:
    """
    Thread-safe in-memory store for device state.

    Parameters
    ----------
    timeout_seconds:
        Seconds of silence after which a device is considered OFFLINE.
        Defaults to 30 (from spec). Override in tests for fast assertions.
    now_fn:
        Callable returning the current UTC datetime. Defaults to
        datetime.now(timezone.utc). Override in tests to control time.
    """

    def __init__(
        self,
        timeout_seconds: int = OFFLINE_TIMEOUT_SECONDS,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.timeout_seconds = timeout_seconds
        self._now: Callable[[], datetime] = now_fn or (
            lambda: datetime.now(timezone.utc)
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _compute_status(self, device: Dict[str, Any]) -> str:
        """Return 'ONLINE' or 'OFFLINE' based on server-received time."""
        received_at: Optional[datetime] = device.get("received_at")
        if received_at is None:
            return "OFFLINE"  # never sent a heartbeat
        elapsed = (self._now() - received_at).total_seconds()
        return "ONLINE" if elapsed <= self.timeout_seconds else "OFFLINE"

    def _serialize(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """Return a plain dict safe to hand to Pydantic / JSON."""
        return {
            "id": device["id"],
            "name": device["name"],
            "status": self._compute_status(device),
            "last_heartbeat": device.get("last_heartbeat"),
            "cpu_usage": device.get("cpu_usage"),
            "signal_strength": device.get("signal_strength"),
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def register(self, device_id: str, name: str) -> Dict[str, Any]:
        """
        Register a new device.

        Raises DeviceAlreadyExistsError if the ID is already taken.
        """
        with self._lock:
            if device_id in self._devices:
                raise DeviceAlreadyExistsError(
                    f"Device '{device_id}' is already registered."
                )
            self._devices[device_id] = {
                "id": device_id,
                "name": name,
                "received_at": None,     # server time of last heartbeat
                "last_heartbeat": None,  # device-reported timestamp
                "cpu_usage": None,
                "signal_strength": None,
            }
            logger.info("Device registered: id=%s name=%s", device_id, name)
            return self._serialize(self._devices[device_id])

    def heartbeat(
        self,
        device_id: str,
        timestamp: datetime,
        status: str,
        cpu_usage: Optional[int] = None,
        signal_strength: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Record a heartbeat for an existing device.

        The server-side received_at is set to now (via self._now) so that
        the ONLINE/OFFLINE decision is based on when WE got the message,
        not on the timestamp the device claims.

        Raises DeviceNotFoundError if device_id is unknown.
        """
        with self._lock:
            if device_id not in self._devices:
                raise DeviceNotFoundError(
                    f"Device '{device_id}' not found. Register it first."
                )
            device = self._devices[device_id]
            device["received_at"] = self._now()   # server clock
            device["last_heartbeat"] = timestamp  # device-reported timestamp
            device["heartbeat_status"] = status
            if cpu_usage is not None:
                device["cpu_usage"] = cpu_usage
            if signal_strength is not None:
                device["signal_strength"] = signal_strength
            logger.info(
                "Heartbeat received: id=%s status=%s cpu=%s signal=%s",
                device_id, status, cpu_usage, signal_strength,
            )
            return self._serialize(device)

    def get(self, device_id: str) -> Dict[str, Any]:
        """
        Return details for a single device.

        Raises DeviceNotFoundError if device_id is unknown.
        """
        with self._lock:
            if device_id not in self._devices:
                raise DeviceNotFoundError(f"Device '{device_id}' not found.")
            return self._serialize(self._devices[device_id])

    def get_all(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return all devices, optionally filtered by status.

        Parameters
        ----------
        status_filter:
            If given, only devices whose computed status matches
            (case-insensitive) are returned. Supported values: ONLINE, OFFLINE.
        """
        with self._lock:
            results = [self._serialize(d) for d in self._devices.values()]
        if status_filter:
            upper = status_filter.upper()
            results = [d for d in results if d["status"] == upper]
        return results

    def summary(self) -> Dict[str, int]:
        """Return fleet-wide totals: total, online, offline."""
        with self._lock:
            all_devices = [self._serialize(d) for d in self._devices.values()]
        total = len(all_devices)
        online = sum(1 for d in all_devices if d["status"] == "ONLINE")
        return {"total": total, "online": online, "offline": total - online}
