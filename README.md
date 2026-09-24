# Mini Device Fleet Monitor

A small REST API that monitors a fleet of simulated IoT devices via **heartbeat tracking**. Each device periodically sends a heartbeat; the server tracks the latest heartbeat for every device and exposes an operator-facing API to view fleet status in real time.

> **ONLINE** — device sent a heartbeat within the last 30 seconds  
> **OFFLINE** — no heartbeat received for more than 30 seconds (or never registered one)

---

## Table of Contents

1. [What the project does](#1-what-the-project-does)  
2. [Design & architecture](#2-design--architecture)  
3. [Prerequisites](#3-prerequisites)  
4. [How to build / install](#4-how-to-build--install)  
5. [How to run the application](#5-how-to-run-the-application)  
6. [How to run the simulator](#6-how-to-run-the-simulator)  
7. [How to run the tests](#7-how-to-run-the-tests)  
8. [Example API requests](#8-example-api-requests)  
9. [Assumptions](#9-assumptions)  
10. [Known limitations](#10-known-limitations)  
11. [What I would improve with one extra day](#11-what-i-would-improve-with-one-extra-day)  
12. [AI Usage](#12-ai-usage)

---

## 1. What the project does

The server exposes five HTTP endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/devices` | Register a new device |
| `POST` | `/devices/{id}/heartbeat` | Record a heartbeat from a device |
| `GET`  | `/devices` | List all devices with live status |
| `GET`  | `/devices/{id}` | Get a single device's details |
| `GET`  | `/summary` | Fleet-wide total / online / offline counts |

A companion simulator script sends heartbeats from 5 virtual devices every 5 seconds. Stopping one device lets you observe it transition to **OFFLINE** after the 30-second window closes.

A live web dashboard is served at **`/dashboard`** and auto-refreshes every 3 seconds.  
Interactive API documentation (Swagger UI) is available at **`/docs`**.

---

## 2. Design & architecture

```
mini-device-fleet-monitor/
├── src/
│   ├── store.py      ← DeviceStore: thread-safe in-memory state + status logic
│   ├── models.py     ← Pydantic request/response schemas (validation)
│   └── main.py       ← FastAPI app — 5 endpoints + /dashboard route
├── tests/
│   └── test_api.py   ← 29 automated tests across 4 required categories
├── simulator/
│   └── simulator.py  ← 5 simulated devices, interactive stop
├── static/
│   └── dashboard.html ← Live fleet dashboard (polls /devices + /summary)
├── requirements.txt
└── README.md
```

### Key design decisions

**Status is computed dynamically, never stored.**  
`DeviceStore._compute_status()` compares the server-recorded receive time
(`received_at`) against `now()` on every read. There is no "ONLINE" or "OFFLINE"
field that can become stale between reads.

**Server clock, not device clock, drives ONLINE/OFFLINE.**  
When a heartbeat arrives, the server records `received_at = datetime.now(utc)`.
The payload `timestamp` is stored as-is for display but is not used in the
timeout calculation. This is resilient to device clock skew.

**Injectable clock for deterministic tests.**  
`DeviceStore` accepts a `now_fn` callable. Tests pass a lambda that returns a
fixed or manually advanced `datetime`, so the 30-second rule is tested
without sleeping.

**Thread safety via `threading.Lock`.**  
FastAPI runs sync route handlers in a thread-pool executor. Every read and
write of `self._devices` is protected by a single `threading.Lock`.

**Framework: FastAPI + uvicorn.**  
FastAPI was chosen because it provides Pydantic-based request validation,
automatic Swagger UI generation, and minimal boilerplate — all appropriate
for a well-documented API within a short time-box.

---

## 3. Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | ≥ 3.11 |
| pip | any recent version |

No Docker or database required. All state is in-memory.

---

## 4. How to build / install

```bash
# Clone the repository
git clone https://github.com/mohittiw07/Mini-Device-Fleet-Monitor.git
cd Mini-Device-Fleet-Monitor

# (Recommended) create a virtual environment
python -m venv .venv
# Activate on macOS / Linux:
source .venv/bin/activate
# Activate on Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

---

## 5. How to run the application

```bash
uvicorn src.main:app --reload
```

The server starts on **`http://localhost:8000`**.

| URL | What you get |
|-----|-------------|
| `http://localhost:8000/docs` | Swagger UI — interactive API explorer |
| `http://localhost:8000/dashboard` | Live fleet dashboard |
| `http://localhost:8000/summary` | JSON fleet summary |

To use a different port:

```bash
uvicorn src.main:app --reload --port 9000
```

---

## 6. How to run the simulator

Open a **second terminal** (keep the API server running in the first).

```bash
python -m simulator.simulator
```

The simulator will:
1. Register 5 devices (`device-01` … `device-05`)
2. Start each on a background thread sending a heartbeat every **5 seconds**
3. Print every heartbeat to the terminal

**To stop one device** (so you can watch it go OFFLINE):

```
> device-05
  ✔ Stopped device-05. Watch it go OFFLINE at /dashboard in ~30 s.
```

Type the device ID and press Enter. After ~30 seconds the device will appear
**OFFLINE** in `/devices`, `/summary`, and the dashboard.

Press **Ctrl+C** to stop all devices and exit.

---

## 7. How to run the tests

```bash
pytest tests/ -v
```

Expected output (29 tests):

```
tests/test_api.py::TestDeviceRegistration::test_register_device_returns_201        PASSED
tests/test_api.py::TestDeviceRegistration::test_new_device_starts_offline          PASSED
tests/test_api.py::TestDeviceRegistration::test_duplicate_registration_returns_409 PASSED
... (26 more)
29 passed in Xs
```

The test file covers all four required categories:

| Category | Tests |
|----------|-------|
| Device registration | 9 |
| Heartbeat handling | 8 |
| Device status | 6 |
| 30-second ONLINE / OFFLINE behaviour | 6 |

---

## 8. Example API requests

### Register a device

```bash
curl -X POST http://localhost:8000/devices \
  -H "Content-Type: application/json" \
  -d '{"id": "device-01", "name": "Lab Device 01"}'
```

```json
{
  "id": "device-01",
  "name": "Lab Device 01",
  "status": "OFFLINE",
  "last_heartbeat": null
}
```

---

### Send a heartbeat

```bash
curl -X POST http://localhost:8000/devices/device-01/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"timestamp": "2026-09-24T09:00:00Z", "status": "OK", "cpu_usage": 42, "signal_strength": -71}'
```

```json
{
  "message": "Heartbeat received",
  "device": {
    "id": "device-01",
    "name": "Lab Device 01",
    "status": "ONLINE",
    "last_heartbeat": "2026-09-24T09:00:00Z",
    "cpu_usage": 42,
    "signal_strength": -71
  }
}
```

---

### List all devices

```bash
curl http://localhost:8000/devices
```

```json
[
  {
    "id": "device-01",
    "name": "Lab Device 01",
    "status": "ONLINE",
    "last_heartbeat": "2026-09-24T09:00:00Z",
    "cpu_usage": 42,
    "signal_strength": -71
  }
]
```

Filter by status:

```bash
curl "http://localhost:8000/devices?status=OFFLINE"
```

---

### Get a single device

```bash
curl http://localhost:8000/devices/device-01
```

---

### Fleet summary

```bash
curl http://localhost:8000/summary
```

```json
{
  "total": 5,
  "online": 4,
  "offline": 1
}
```

---

## 9. Assumptions

1. **Server clock is authoritative for ONLINE/OFFLINE.** The payload `timestamp`
   is stored for display only. Devices can have clock skew without affecting
   their status classification.

2. **In-memory store is sufficient.** The spec describes a 3-hour exercise;
   persistent storage would add complexity without changing correctness.

3. **Device IDs are case-sensitive strings.** `device-01` and `DEVICE-01`
   are treated as different devices.

4. **"within the last 30 seconds" is inclusive.** A device whose last heartbeat
   arrived exactly 30 seconds ago is still **ONLINE** (`elapsed <= 30`).

5. **Concurrent simulators are allowed.** The `threading.Lock` inside
   `DeviceStore` makes simultaneous heartbeats from multiple threads safe.

6. **A device can be re-registered after a restart.** The API returns 409
   for duplicates; the simulator handles this gracefully and continues.

---

## 10. Known limitations

- **No persistence.** Restarting the server loses all device registrations
  and heartbeat history.
- **No authentication.** Any client can register or send heartbeats for
  any device.
- **No delete endpoint.** Once registered, a device cannot be removed.
- **No pagination.** `GET /devices` returns all devices; large fleets may
  produce a large response.
- **Single-node only.** The in-memory store cannot be shared across multiple
  server instances.

---

## 11. What I would improve with one extra day

1. **Persistent storage** — swap `DeviceStore` for a SQLite or Redis backend
   so state survives restarts. The store interface (`register`, `heartbeat`,
   `get`, `get_all`, `summary`) is already abstracted, making the swap clean.

2. **DELETE /devices/{id}** — allow decommissioning a device.

3. **Pagination & sorting** — `GET /devices?page=2&limit=20&sort=status`
   for large fleets.

4. **WebSocket push for the dashboard** — replace polling with a
   `GET /ws/fleet` WebSocket feed so the UI updates instantly instead of
   every 3 seconds.

5. **Docker & docker-compose** — a single `docker compose up` to start both
   the API and the simulator without manual setup.

6. **Configuration via environment variables** — `OFFLINE_TIMEOUT_SECONDS`,
   `PORT`, `LOG_LEVEL` read from the environment so the binary needs no
   rebuild to change behaviour.

7. **Structured JSON logging** — replace the plain text logger with JSON
   output so logs can be ingested by Datadog / CloudWatch / Loki.

---

## 12. AI Usage

**Tools used:** Antigravity (Google DeepMind coding assistant) — used throughout
the session to scaffold and implement this project.

**What it was used for:**  
- Generating the initial project structure and file stubs  
- Drafting Pydantic models and FastAPI route handlers  
- Writing the test suite, particularly the time-injection pattern for the
  30-second ONLINE/OFFLINE tests  
- Drafting this README

**One thing I changed from the AI suggestion:**  
The AI initially proposed using the device-reported `timestamp` field to decide
ONLINE/OFFLINE status. I changed this to use the **server-received time**
(`received_at = datetime.now(utc)` recorded when the heartbeat arrives). This
is more correct: if a device sends an old timestamp in its payload, it should
still count as recently seen by the server.

**One thing I personally verified before submitting:**  
I ran the full test suite (`pytest tests/ -v`) and manually exercised the
simulator — registering all 5 devices, stopping `device-05`, and confirming
in `/summary` and `/dashboard` that it transitioned to OFFLINE after 30 seconds.
