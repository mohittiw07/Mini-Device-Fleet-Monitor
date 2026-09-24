"""
Automated tests for the Mini Device Fleet Monitor API.

Test categories (matching spec requirements):
  1. Device registration
  2. Heartbeat handling
  3. Device status
  4. The 30-second ONLINE / OFFLINE behaviour

Run:
    pytest tests/ -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import src.main as main_module
from src.main import app
from src.store import DeviceStore


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_client(store: DeviceStore) -> TestClient:
    """
    Point the application's module-level store at *store* and return a
    TestClient.  Because route handlers look up `store` by name in the module
    globals at call time (not at definition time), swapping it here is safe.
    """
    main_module.store = store
    return TestClient(app)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── 1. Device Registration ────────────────────────────────────────────────────


class TestDeviceRegistration:
    """Tests for POST /devices."""

    def setup_method(self):
        self.store = DeviceStore()
        self.client = make_client(self.store)

    def test_register_device_returns_201(self):
        resp = self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        assert resp.status_code == 201

    def test_register_device_response_shape(self):
        resp = self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        data = resp.json()
        assert data["id"] == "d-01"
        assert data["name"] == "Device 01"
        assert data["last_heartbeat"] is None

    def test_new_device_starts_offline(self):
        """A freshly registered device with no heartbeat must be OFFLINE."""
        resp = self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        assert resp.json()["status"] == "OFFLINE"

    def test_duplicate_registration_returns_409(self):
        self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        resp = self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        assert resp.status_code == 409

    def test_missing_name_returns_422(self):
        resp = self.client.post("/devices", json={"id": "d-01"})
        assert resp.status_code == 422

    def test_missing_id_returns_422(self):
        resp = self.client.post("/devices", json={"name": "Device 01"})
        assert resp.status_code == 422

    def test_empty_id_returns_422(self):
        resp = self.client.post("/devices", json={"id": "", "name": "Device 01"})
        assert resp.status_code == 422

    def test_list_empty_fleet(self):
        resp = self.client.get("/devices")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_shows_registered_device(self):
        self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        resp = self.client.get("/devices")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == "d-01"


# ── 2. Heartbeat Handling ─────────────────────────────────────────────────────


class TestHeartbeatHandling:
    """Tests for POST /devices/{id}/heartbeat."""

    def setup_method(self):
        self.store = DeviceStore()
        self.client = make_client(self.store)
        # Pre-register a device for most tests
        self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})

    def test_heartbeat_returns_200(self):
        resp = self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": now_utc().isoformat(), "status": "OK"},
        )
        assert resp.status_code == 200

    def test_heartbeat_response_contains_message_and_device(self):
        resp = self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": now_utc().isoformat(), "status": "OK"},
        )
        body = resp.json()
        assert "message" in body
        assert "device" in body
        assert body["device"]["id"] == "d-01"

    def test_heartbeat_stores_last_heartbeat_timestamp(self):
        ts = now_utc().isoformat()
        self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": ts, "status": "OK"},
        )
        detail = self.client.get("/devices/d-01").json()
        assert detail["last_heartbeat"] is not None

    def test_heartbeat_with_optional_fields(self):
        resp = self.client.post(
            "/devices/d-01/heartbeat",
            json={
                "timestamp": now_utc().isoformat(),
                "status": "OK",
                "cpu_usage": 42,
                "signal_strength": -71,
            },
        )
        device = resp.json()["device"]
        assert device["cpu_usage"] == 42
        assert device["signal_strength"] == -71

    def test_heartbeat_unknown_device_returns_404(self):
        resp = self.client.post(
            "/devices/nonexistent/heartbeat",
            json={"timestamp": now_utc().isoformat(), "status": "OK"},
        )
        assert resp.status_code == 404

    def test_heartbeat_invalid_timestamp_returns_422(self):
        resp = self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": "not-a-date", "status": "OK"},
        )
        assert resp.status_code == 422

    def test_heartbeat_missing_status_returns_422(self):
        resp = self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": now_utc().isoformat()},
        )
        assert resp.status_code == 422

    def test_cpu_usage_above_100_returns_422(self):
        resp = self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": now_utc().isoformat(), "status": "OK", "cpu_usage": 101},
        )
        assert resp.status_code == 422


# ── 3. Device Status ──────────────────────────────────────────────────────────


class TestDeviceStatus:
    """Tests for GET /devices, GET /devices/{id}, GET /summary."""

    def setup_method(self):
        self.store = DeviceStore()
        self.client = make_client(self.store)

    def test_get_device_not_found_returns_404(self):
        resp = self.client.get("/devices/ghost")
        assert resp.status_code == 404

    def test_get_device_returns_correct_fields(self):
        self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        resp = self.client.get("/devices/d-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "d-01"
        assert data["name"] == "Device 01"
        assert "status" in data
        assert "last_heartbeat" in data

    def test_summary_empty_fleet(self):
        resp = self.client.get("/summary")
        assert resp.status_code == 200
        assert resp.json() == {"total": 0, "online": 0, "offline": 0}

    def test_summary_counts_correctly(self):
        # Register two devices; only d-01 sends a heartbeat
        self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        self.client.post("/devices", json={"id": "d-02", "name": "Device 02"})
        self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": now_utc().isoformat(), "status": "OK"},
        )
        summary = self.client.get("/summary").json()
        assert summary["total"] == 2
        assert summary["online"] == 1
        assert summary["offline"] == 1

    def test_filter_by_online_status(self):
        self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        self.client.post("/devices", json={"id": "d-02", "name": "Device 02"})
        self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": now_utc().isoformat(), "status": "OK"},
        )
        online = self.client.get("/devices?status=ONLINE").json()
        assert len(online) == 1
        assert online[0]["id"] == "d-01"

    def test_filter_by_offline_status(self):
        self.client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        self.client.post("/devices", json={"id": "d-02", "name": "Device 02"})
        self.client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": now_utc().isoformat(), "status": "OK"},
        )
        offline = self.client.get("/devices?status=OFFLINE").json()
        assert len(offline) == 1
        assert offline[0]["id"] == "d-02"


# ── 4. 30-Second ONLINE / OFFLINE Behaviour ───────────────────────────────────


class TestOnlineOfflineBehaviour:
    """
    Tests the core timeout rule from the spec:
        ONLINE  if heartbeat received within the last 30 seconds
        OFFLINE if no heartbeat has been received for more than 30 seconds

    Strategy: inject a controllable `now_fn` into DeviceStore so we can
    advance the clock without sleeping.
    """

    def _make(self, now_fn) -> tuple[TestClient, DeviceStore]:
        """Create a store with a controlled clock and a matching TestClient."""
        store = DeviceStore(now_fn=now_fn)
        client = make_client(store)
        return client, store

    # ── Basic ONLINE / OFFLINE cases ──────────────────────────────────────────

    def test_no_heartbeat_device_is_offline(self):
        """Brand-new device (no heartbeat) must be OFFLINE."""
        t0 = now_utc()
        client, _ = self._make(lambda: t0)
        client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        assert client.get("/devices/d-01").json()["status"] == "OFFLINE"

    def test_recent_heartbeat_device_is_online(self):
        """Device is ONLINE immediately after a heartbeat."""
        t0 = now_utc()
        client, _ = self._make(lambda: t0)
        client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": t0.isoformat(), "status": "OK"},
        )
        assert client.get("/devices/d-01").json()["status"] == "ONLINE"

    # ── Boundary: exactly 30 seconds ─────────────────────────────────────────

    def test_device_still_online_at_exactly_30_seconds(self):
        """At exactly 30 s the device should still be ONLINE (≤ timeout)."""
        t0 = now_utc()
        client, controlled_store = self._make(lambda: t0)
        client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": t0.isoformat(), "status": "OK"},
        )
        # Advance clock to exactly 30 s
        at_30s = t0 + timedelta(seconds=30)
        controlled_store._now = lambda: at_30s
        assert client.get("/devices/d-01").json()["status"] == "ONLINE"

    def test_device_goes_offline_after_30_seconds(self):
        """At 31 s past the last heartbeat the device must be OFFLINE."""
        t0 = now_utc()
        client, controlled_store = self._make(lambda: t0)
        client.post("/devices", json={"id": "d-01", "name": "Device 01"})
        client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": t0.isoformat(), "status": "OK"},
        )
        # Advance clock to 31 s
        at_31s = t0 + timedelta(seconds=31)
        controlled_store._now = lambda: at_31s
        assert client.get("/devices/d-01").json()["status"] == "OFFLINE"

    # ── Summary reflects timeout ───────────────────────────────────────────────

    def test_summary_updates_when_device_goes_offline(self):
        """
        Two devices send heartbeats → both ONLINE.
        Advance clock 31 s → both OFFLINE.
        Summary must track this correctly.
        """
        t0 = now_utc()
        client, controlled_store = self._make(lambda: t0)

        for did in ["d-01", "d-02"]:
            client.post("/devices", json={"id": did, "name": f"Device {did}"})
            client.post(
                f"/devices/{did}/heartbeat",
                json={"timestamp": t0.isoformat(), "status": "OK"},
            )

        assert client.get("/summary").json() == {"total": 2, "online": 2, "offline": 0}

        # Advance clock past timeout
        controlled_store._now = lambda: t0 + timedelta(seconds=31)
        assert client.get("/summary").json() == {"total": 2, "online": 0, "offline": 2}

    def test_second_heartbeat_resets_online_window(self):
        """
        Device goes silent → OFFLINE.
        Sends a new heartbeat → ONLINE again.
        """
        t0 = now_utc()
        client, controlled_store = self._make(lambda: t0)
        client.post("/devices", json={"id": "d-01", "name": "Device 01"})

        # First heartbeat
        client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": t0.isoformat(), "status": "OK"},
        )

        # Advance 31 s → OFFLINE
        t_offline = t0 + timedelta(seconds=31)
        controlled_store._now = lambda: t_offline
        assert client.get("/devices/d-01").json()["status"] == "OFFLINE"

        # Device sends a new heartbeat at t_offline
        controlled_store._now = lambda: t_offline  # still "now"
        client.post(
            "/devices/d-01/heartbeat",
            json={"timestamp": t_offline.isoformat(), "status": "OK"},
        )
        assert client.get("/devices/d-01").json()["status"] == "ONLINE"
