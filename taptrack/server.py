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

from . import analysis, config, notify, report, synth
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
    """Seed 14 days of synthetic data if storage has none (or it's stale). Demo-replay rows from a
    previous session are cleared so they don't skew the 14-day pattern."""
    store.clear_source("demo")
    today = time.strftime("%Y-%m-%d")
    # reseed once per day so "today" always has this morning's synthetic history up to server start
    if store.get_setting("seeded_on") != today and config.env("AUTO_SEED", "true").lower() != "false":
        stats = synth.load_into(store)
        store.set_setting("seeded_on", today)
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
        bridge.listeners.append(_fallback_alert)
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
AGENT_STALE_S = 30


def agent_alive() -> bool:
    return time.time() - state.get("agent_seen", 0) < AGENT_STALE_S


def _fallback_alert(row):
    """The Fetch.ai agent decides notifications. If it isn't running, the server still sends the red-score
    alert (and in DEMO_MODE an update after every live check, so a phone buzzes during the pitch)."""
    if agent_alive() or row.get("score") is None or row.get("source") == "synthetic":
        return
    demo_all = config.DEMO_MODE and config.env("DEMO_ALERT_ALL_CHECKS", "true").lower() != "false"
    if row.get("level") == "low" or demo_all:
        r = notify.send("caregiver", notify.red_alert(row), store(), kind="caregiver_alert", source="server (agent offline)")
        hub.publish({"type": "notification", "kind": "caregiver_alert", "sent": r.get("ok"), "error": r.get("error")})


@app.get("/api/status")
def status():
    b = state.get("bridge")
    return {"features": {**config.features(), "agent": agent_alive(), "photon": notify.photon_health().get("ok", False)},
            "storage": store().kind,
            "device": b.status() if b else {"state": "off"},
            "patient": {"id": config.PATIENT_ID, "name": config.PATIENT_NAME, "dose_times": config.DOSE_TIMES,
                        "record": store().get_setting("patient")},
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
    state: float | None = None  # simulated motor state 0..1 (e.g. 0.1 = wearing off) for demos


@app.post("/api/check/start")
def start_check(body: CheckIn | None = None):
    b = state.get("bridge")
    if not b:
        raise HTTPException(503, "bridge disabled")
    forced = body.state if body else None
    simulate = bool(body and body.simulate) or forced is not None or not (b.device and b.device.connected)
    b.request_check(simulate=simulate, state=forced)
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


@app.post("/api/report")
def make_report():
    r = report.generate(store())
    hub.publish({"type": "report", "report": {k: v for k, v in r.items() if k != "facts"}})
    return r


@app.get("/api/report/latest")
def latest_report():
    return store().get_setting("latest_report") or {}


@app.get("/api/patient")
def patient():
    return store().get_setting("patient") or {}


class NotifyIn(BaseModel):
    kind: str                      # caregiver_alert | missed_reminder | report_sent | custom
    to: str = "caregiver"
    text: str | None = None
    check: dict | None = None
    slot: dict | None = None
    doctor: str | None = None
    appointment: str | None = None
    onset_minutes: float | None = None
    source: str = "fetch.ai agent"


@app.post("/api/notify")
def send_notification(n: NotifyIn):
    """Called by the Fetch.ai agent when it decides to notify; formats and sends via Photon iMessage."""
    if n.text:
        text = n.text
    elif n.kind == "caregiver_alert" and n.check:
        text = notify.red_alert(n.check)
    elif n.kind == "missed_reminder" and n.slot:
        text = notify.missed_reminder(n.slot)
    elif n.kind == "report_sent":
        text = notify.report_sent(n.doctor or "the neurologist", n.appointment, n.onset_minutes)
    else:
        raise HTTPException(400, "need text or kind-specific fields")
    text, _ = report.guard(text)
    r = notify.send(n.to, text, store(), kind=n.kind, source=n.source)
    hub.publish({"type": "notification", "kind": n.kind, "to": n.to, "text": text, "sent": r.get("ok"), "error": r.get("error")})
    return {**r, "text": text}


@app.post("/api/notify/test")
def test_notification():
    text = f"TapTrack test message: notifications for {notify.first_name()} are working."
    r = notify.send("caregiver", text, store(), kind="test_message", source="dashboard")
    hub.publish({"type": "notification", "kind": "test_message", "sent": r.get("ok"), "error": r.get("error")})
    return {**r, "text": text}


@app.post("/api/chat")
def chat(body: dict):
    """Inbound iMessage (via the Photon sidecar) or ASI:One question -> short answer from our data."""
    sender = body.get("from") or body.get("sender") or "unknown"
    reply = notify.chat_reply(store(), sender, body.get("text", ""), body.get("role", "caregiver"))
    store().add_action("chat_reply", {"to": sender[-4:] if sender else "?", "q": body.get("text", "")[:120], "text": reply})
    hub.publish({"type": "agent_action", "kind": "chat_reply", "detail": {"text": reply}})
    return {"reply": reply}


class Heartbeat(BaseModel):
    address: str | None = None
    name: str | None = None


@app.post("/api/agent/heartbeat")
def agent_heartbeat(h: Heartbeat):
    state["agent_seen"] = time.time()
    state["agent"] = h.model_dump()
    return {"ok": True}


@app.get("/api/agent")
def agent_status():
    return {"alive": agent_alive(), "last_seen": state.get("agent_seen"), **(state.get("agent") or {})}


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
