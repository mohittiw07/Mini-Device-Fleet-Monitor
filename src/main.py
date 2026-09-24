"""
Mini Device Fleet Monitor — FastAPI application.

Endpoints
---------
POST   /devices                  Register a new device
POST   /devices/{id}/heartbeat   Receive a heartbeat from a device
GET    /devices                  List all devices (optional ?status= filter)
GET    /devices/{id}             Get a single device's details
GET    /summary                  Fleet-wide summary (total / online / offline)
GET    /dashboard                Live HTML dashboard (optional UI enhancement)

Run
---
    uvicorn src.main:app --reload
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .models import (
    DeviceResponse,
    HeartbeatRequest,
    RegisterDeviceRequest,
    SummaryResponse,
)
from .store import DeviceAlreadyExistsError, DeviceNotFoundError, DeviceStore

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App & store ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Mini Device Fleet Monitor",
    description=(
        "Monitor a fleet of simulated IoT devices via heartbeat tracking. "
        "A device is ONLINE if it sent a heartbeat within the last 30 seconds; "
        "otherwise it is OFFLINE."
    ),
    version="1.0.0",
)

# Module-level store — replaced with a fresh DeviceStore in tests via
# `import src.main as main_module; main_module.store = DeviceStore()`
store: DeviceStore = DeviceStore()


# ── Routes ────────────────────────────────────────────────────────────────────


@app.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=201,
    summary="Register a new device",
    tags=["devices"],
)
def register_device(request: RegisterDeviceRequest) -> DeviceResponse:
    """
    Register a device by supplying a unique **id** and a **name**.

    Returns 409 if a device with the same id is already registered.
    """
    try:
        result = store.register(request.id, request.name)
        return result
    except DeviceAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/devices/{device_id}/heartbeat",
    status_code=200,
    summary="Receive a heartbeat from a device",
    tags=["devices"],
)
def receive_heartbeat(device_id: str, request: HeartbeatRequest) -> dict:
    """
    Record a heartbeat for an already-registered device.

    The server records the **server-side receive time** for the ONLINE/OFFLINE
    decision, so the device clock skew does not affect status accuracy.

    Returns 404 if the device has not been registered.
    """
    try:
        updated = store.heartbeat(
            device_id,
            timestamp=request.timestamp,
            status=request.status,
            cpu_usage=request.cpu_usage,
            signal_strength=request.signal_strength,
        )
        return {"message": "Heartbeat received", "device": updated}
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get(
    "/devices",
    response_model=List[DeviceResponse],
    summary="List all registered devices",
    tags=["devices"],
)
def list_devices(
    status: Optional[str] = Query(
        None,
        description="Filter by status: ONLINE or OFFLINE",
        pattern="^(ONLINE|OFFLINE|online|offline)$",
    )
) -> List[DeviceResponse]:
    """
    Return all registered devices with their current computed status.

    Optionally filter by **?status=ONLINE** or **?status=OFFLINE**.
    """
    return store.get_all(status_filter=status)


@app.get(
    "/devices/{device_id}",
    response_model=DeviceResponse,
    summary="Get a single device",
    tags=["devices"],
)
def get_device(device_id: str) -> DeviceResponse:
    """
    Return details for one device.

    Returns 404 if the device has not been registered.
    """
    try:
        return store.get(device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get(
    "/summary",
    response_model=SummaryResponse,
    summary="Fleet-wide status summary",
    tags=["fleet"],
)
def fleet_summary() -> SummaryResponse:
    """
    Return a count of total / online / offline devices across the entire fleet.
    """
    return store.summary()


# ── Optional UI ───────────────────────────────────────────────────────────────


@app.get(
    "/dashboard",
    response_class=HTMLResponse,
    include_in_schema=False,  # keep Swagger docs clean
)
def dashboard() -> HTMLResponse:
    """Serve the live fleet dashboard HTML page."""
    static_path = os.path.join(
        os.path.dirname(__file__), "..", "static", "dashboard.html"
    )
    try:
        with open(static_path, encoding="utf-8") as fh:
            return HTMLResponse(content=fh.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard file not found.")
