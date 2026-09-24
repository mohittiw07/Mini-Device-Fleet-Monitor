#!/usr/bin/env python3
"""
Device Fleet Simulator

Simulates 5 devices sending periodic heartbeats to the fleet monitor API.
One or more devices can be stopped interactively so you can watch them
transition to OFFLINE after the 30-second timeout.

Usage
-----
    # From the project root (after starting the API server):
    python -m simulator.simulator

    # Or directly:
    python simulator/simulator.py

Interactive commands
--------------------
    Type a device ID (e.g. "device-05") and press Enter to stop that device.
    Press Ctrl+C to stop all devices and exit.
"""

from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime, timezone

import requests

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
HEARTBEAT_INTERVAL_SECONDS = 5

DEVICES = [
    {"id": "device-01", "name": "Lab Device 01"},
    {"id": "device-02", "name": "Lab Device 02"},
    {"id": "device-03", "name": "Lab Device 03"},
    {"id": "device-04", "name": "Lab Device 04"},
    {"id": "device-05", "name": "Lab Device 05"},
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Stop-event registry ───────────────────────────────────────────────────────

# Maps device_id → threading.Event; set the event to stop that device's loop.
_stop_events: dict[str, threading.Event] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _register_device(device: dict) -> bool:
    """
    Register the device with the API.
    Returns True on success (including 409 already-registered).
    """
    try:
        resp = requests.post(f"{BASE_URL}/devices", json=device, timeout=5)
        if resp.status_code == 201:
            logger.info("✔ Registered  %s  (%s)", device["id"], device["name"])
            return True
        if resp.status_code == 409:
            logger.info("↺ Already registered: %s", device["id"])
            return True
        logger.error("✘ Register failed %s → HTTP %s", device["id"], resp.status_code)
        return False
    except requests.ConnectionError:
        logger.error("✘ Cannot reach API at %s — is the server running?", BASE_URL)
        return False


def _send_heartbeat(device_id: str) -> None:
    """POST one heartbeat for *device_id*."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OK",
        # Optional extended fields (spec allows these)
        "cpu_usage": abs(hash(device_id + str(datetime.now().second))) % 80 + 10,
        "signal_strength": -(abs(hash(device_id)) % 30 + 50),  # e.g. -50 to -80
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/devices/{device_id}/heartbeat",
            json=payload,
            timeout=5,
        )
        if resp.status_code == 200:
            logger.info(
                "♥ %s  heartbeat OK  (cpu=%s%%  signal=%s dBm)",
                device_id,
                payload["cpu_usage"],
                payload["signal_strength"],
            )
        else:
            logger.warning("! %s  heartbeat HTTP %s", device_id, resp.status_code)
    except requests.RequestException as exc:
        logger.error("✘ %s  heartbeat error: %s", device_id, exc)


def _device_loop(device: dict, stop_event: threading.Event) -> None:
    """
    Run in a background thread.
    Sends a heartbeat every HEARTBEAT_INTERVAL_SECONDS until *stop_event* fires.
    """
    device_id = device["id"]
    logger.info("▶ %s  started  (heartbeat every %ds)", device_id, HEARTBEAT_INTERVAL_SECONDS)
    while not stop_event.is_set():
        _send_heartbeat(device_id)
        # Use Event.wait so we can be interrupted immediately on stop
        stop_event.wait(timeout=HEARTBEAT_INTERVAL_SECONDS)
    logger.info("■ %s  stopped.  Will be OFFLINE in ~30 s.", device_id)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print()
    print("=" * 62)
    print("   Mini Device Fleet Monitor — Device Simulator")
    print("=" * 62)
    print(f"   API endpoint : {BASE_URL}")
    print(f"   Heartbeat    : every {HEARTBEAT_INTERVAL_SECONDS} seconds")
    print(f"   Devices      : {len(DEVICES)}")
    print("=" * 62)
    print()

    # ── 1. Register all devices ──────────────────────────────────────────────
    print("Registering devices...")
    registered = []
    for device in DEVICES:
        if _register_device(device):
            registered.append(device)

    if not registered:
        print("\nNo devices could be registered. Is the API server running?")
        sys.exit(1)

    print()

    # ── 2. Start heartbeat threads ────────────────────────────────────────────
    threads: list[threading.Thread] = []
    for device in registered:
        event = threading.Event()
        _stop_events[device["id"]] = event
        t = threading.Thread(
            target=_device_loop,
            args=(device, event),
            name=device["id"],
            daemon=True,  # exits when the main thread exits
        )
        t.start()
        threads.append(t)

    print()
    print("All devices are now running.")
    print()
    print("  To STOP a specific device  →  type its ID and press Enter")
    print("  To stop ALL devices        →  press Ctrl+C")
    print()
    print(f"  Device IDs: {[d['id'] for d in registered]}")
    print()
    print("  (A stopped device becomes OFFLINE after 30 seconds.)")
    print("  Watch the dashboard at http://localhost:8000/dashboard")
    print()

    # ── 3. Interactive command loop ───────────────────────────────────────────
    try:
        while True:
            try:
                cmd = input("> ").strip()
            except EOFError:
                # Non-interactive mode (e.g. piped input) — just keep running
                threading.Event().wait()
                break

            if not cmd:
                continue

            if cmd in _stop_events:
                if _stop_events[cmd].is_set():
                    print(f"  {cmd} is already stopped.")
                else:
                    _stop_events[cmd].set()
                    print(f"  ✔ Stopped {cmd}. Watch it go OFFLINE at /dashboard in ~30 s.")
            else:
                active = [did for did, ev in _stop_events.items() if not ev.is_set()]
                print(f"  Unknown ID '{cmd}'. Active devices: {active}")

    except KeyboardInterrupt:
        print("\n\nStopping all devices...")
        for event in _stop_events.values():
            event.set()
        print("Done. Goodbye.")


if __name__ == "__main__":
    main()
