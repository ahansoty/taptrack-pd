"""FastAPI app: REST data, websocket live results, and the dashboard (static/).

Run: python -m taptrack.server   (or uvicorn taptrack.server:app)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analysis, config, synth
from .bridge import Bridge
from .storage import get_store

log = logging.getLogger("taptrack.server")
STATIC = config.ROOT / "static"


class Hub:
    """Websocket fan-out. publish() is safe to call from the bridge thread."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.recent: list[dict] = []

    def publish(self, event: dict):
        event = {"at": time.time(), **event}
        self.recent = (self.recent + [event])[-50:]
        if self.loop and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._send(event), self.loop)

    async def _send(self, event):
        msg = json.dumps(event, default=float)
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                self.clients.discard(ws)


hub = Hub()
state: dict = {}


def _ensure_seed(store):
    """Seed 14 days of synthetic data if storage has none (or it's stale)."""
    latest = store.checks(time.time() - 2 * 86400, source="synthetic")
    if not latest and config.env("AUTO_SEED", "true").lower() != "false":
        stats = synth.load_into(store)
        log.info("Seeded synthetic data: %s", stats)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    hub.loop = asyncio.get_running_loop()
    store = get_store()
    _ensure_seed(store)
    state["store"] = store
    bridge = None
    if config.env("BRIDGE", "true").lower() != "false":
        bridge = Bridge(store, hub.publish)
        from . import integrations
        integrations.register(bridge, store, hub.publish)
        bridge.start()
    state["bridge"] = bridge
    yield
    if bridge:
        bridge.stop()
        bridge.join(timeout=3)


app = FastAPI(title="TapTrack PD", lifespan=lifespan)


def store():
    return state["store"]


# ------------------------------------------------------------------ pages
@app.get("/")
def clinician_page():
    return FileResponse(STATIC / "clinician.html")


@app.get("/caregiver")
def caregiver_page():
    return FileResponse(STATIC / "caregiver.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ------------------------------------------------------------------ data
@app.get("/api/status")
def status():
    b = state.get("bridge")
    return {"features": config.features(), "storage": store().kind,
            "device": b.status() if b else {"state": "off"},
            "patient": {"id": config.PATIENT_ID, "name": config.PATIENT_NAME, "dose_times": config.DOSE_TIMES,
                        **(state.get("patient") or {})},
            "baseline_set": store().get_setting("baseline") is not None}


@app.get("/api/today")
def today(date: str | None = None):
    start = analysis.day_start() if not date else time.mktime(time.strptime(date, "%Y-%m-%d"))
    end = start + 86400
    s = store()
    checks = s.checks(start, end)
    return {"date": time.strftime("%Y-%m-%d", time.localtime(start)), "start": start,
            "checks": checks, "doses": s.doses(start, end), "passive": s.passive(start, end),
            "missed": analysis.missed_checks(checks, start, min(end, time.time()))}


@app.get("/api/checks")
def checks(days: int = 14):
    return store().checks(analysis.day_start() - (days - 1) * 86400)


@app.get("/api/checks/latest")
def latest():
    return store().latest_check() or {}


@app.get("/api/heatmap")
def heatmap(days: int = 14):
    c = store().checks(analysis.day_start() - (days - 1) * 86400)
    return analysis.heatmap(c, days)


@app.get("/api/summary")
def summary(days: int = 14):
    return analysis.summary(store(), days)


@app.get("/api/caregiver")
def caregiver():
    s = store()
    now = time.time()
    start = analysis.day_start(now)
    checks_today = s.checks(start)
    missed_today = analysis.missed_checks(checks_today, start, now)
    week = s.checks(start - 6 * 86400)
    latest = s.latest_check()
    last_dose = s.last_dose_before(now)
    next_dose = None
    for hhmm in config.DOSE_TIMES:
        h, m = (int(x) for x in hhmm.split(":"))
        t = start + h * 3600 + m * 60
        if t > now:
            next_dose = t
            break
    return {"latest": latest, "last_dose": last_dose, "next_dose": next_dose,
            "checks_today": len(checks_today), "missed_today": missed_today,
            "missed_7d": len(analysis.missed_checks(week, start - 6 * 86400, now)),
            "expected_so_far": len(checks_today) + len(missed_today),
            "actions": s.actions(10)}


@app.get("/api/actions")
def actions(limit: int = 20):
    return store().actions(limit)


@app.get("/api/outbox")
def outbox(limit: int = 20):
    return store().outbox(limit)


class DoseIn(BaseModel):
    source: str = "dashboard"


@app.post("/api/dose")
def dose(body: DoseIn | None = None):
    b = state.get("bridge")
    src = (body.source if body else "dashboard")
    if b:
        b.request_dose(src)
        return {"queued": True}
    return {"ts": store().add_dose(source=src)}


class CheckIn(BaseModel):
    simulate: bool = False


@app.post("/api/check/start")
def start_check(body: CheckIn | None = None):
    b = state.get("bridge")
    if not b:
        raise HTTPException(503, "bridge disabled")
    simulate = bool(body and body.simulate) or not (b.device and b.device.connected)
    b.request_check(simulate=simulate)
    return {"queued": True, "simulate": simulate}


@app.post("/api/seed")
def seed(days: int = 14):
    return synth.load_into(store(), days=days)


class ActionIn(BaseModel):
    kind: str
    detail: dict = {}


@app.post("/api/actions")
def add_action(a: ActionIn):
    """Used by the Fetch.ai agent to record what it did (shown on the dashboards)."""
    store().add_action(a.kind, a.detail)
    hub.publish({"type": "agent_action", "kind": a.kind, "detail": a.detail})
    return {"ok": True}


@app.get("/api/events")
def recent_events():
    return hub.recent


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    hub.clients.add(websocket)
    b = state.get("bridge")
    await websocket.send_text(json.dumps({"type": "hello", "device": b.status() if b else None}, default=float))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(websocket)


@app.exception_handler(Exception)
async def on_error(request, exc):
    log.exception("API error")
    return JSONResponse({"error": str(exc)}, status_code=500)


def main():
    import uvicorn

    uvicorn.run("taptrack.server:app", host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
