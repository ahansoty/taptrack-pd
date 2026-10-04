"""Phone notifications through Photon Spectrum (iMessage) via the Node sidecar (photon/sidecar.mjs),
plus the two-way caregiver chat that answers from TapTrack data.

Who decides: the Fetch.ai care agent (agent/taptrack_agent.py) decides when to notify and calls
POST /api/notify. If the agent is not running, the server sends the red-score alert itself so the
caregiver is never left uninformed. Messages describe patterns only, never medication advice.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

import httpx

from . import analysis, config, report

log = logging.getLogger("taptrack.notify")


def first_name() -> str:
    return (config.PATIENT_NAME or "the patient").split(" ")[0]


def _clock(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%I:%M %p").lstrip("0")


def _hm(minutes) -> str:
    if minutes is None:
        return "no dose logged before it"
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m} min after the last dose" if h else f"{m} min after the last dose"


# ------------------------------------------------------------------ message templates
def red_alert(check: dict, baseline_mean: float = 85) -> str:
    level_word = {"low": "much lower than usual", "fair": "lower than usual", "good": "close to usual"}.get(check.get("level"), "recorded")
    alert = check.get("level") == "low"
    return (f"{'TapTrack alert' if alert else 'TapTrack update'}: {first_name()}'s {_clock(check['ts'])} check was {level_word} "
            f"(score {round(check['score'])}; usual is about {round(baseline_mean)}). It was {_hm(check.get('minutes_since_dose'))}. "
            f"Reply 'today' for a summary.")


def missed_reminder(slot: dict) -> str:
    return (f"Hi {first_name()}, your {_clock(slot['ts'])} TapTrack check is waiting. When you're ready, press the blue "
            f"button on your watch. It takes about a minute.")


def report_sent(doctor: str, appointment: str | None, onset_minutes) -> str:
    when = f" Proposed follow-up: {appointment}." if appointment else ""
    pattern = f" The report shows scores dropping about {onset_minutes / 60:.1f} h after doses." if onset_minutes else ""
    return f"TapTrack sent {first_name()}'s 14-day visit report to {doctor} and requested a follow-up visit.{when}{pattern}"


# ------------------------------------------------------------------ transport
def send(to: str, text: str, store=None, kind: str = "message", source: str = "server") -> dict:
    """to: 'caregiver' | 'patient' | E.164. Never raises."""
    url = f"http://127.0.0.1:{config.env('PHOTON_PORT', '8790')}/send"
    try:
        r = httpx.post(url, json={"to": to, "text": text}, timeout=20).json()
    except Exception as ex:
        r = {"ok": False, "error": f"Photon sidecar not running ({ex.__class__.__name__}); start: node photon/sidecar.mjs"}
    if store is not None:
        store.add_action(kind, {"to": to, "text": text, "sent": bool(r.get("ok")), "error": r.get("error"), "source": source})
    return r


def photon_health() -> dict:
    try:
        return httpx.get(f"http://127.0.0.1:{config.env('PHOTON_PORT', '8790')}/health", timeout=3).json()
    except Exception:
        return {"ok": False, "status": "sidecar not running"}


# ------------------------------------------------------------------ two-way chat
ASKS_ADVICE = re.compile(r"\b(should|can|could|may)\b.*\b(take|give|skip|increase|decrease|change|more|less|extra|double)\b"
                         r".*\b(dose|pill|medicine|medication|levodopa|sinemet)\b", re.I)


def day_summary(store, day: dt.date) -> str:
    start = dt.datetime.combine(day, dt.time()).timestamp()
    end = min(start + 86400, time.time())
    checks = [c for c in store.checks(start, start + 86400) if c.get("score") is not None]
    doses = store.doses(start, start + 86400)
    missed = analysis.missed_checks(checks, start, end)
    label = "Today" if day == dt.date.today() else ("Yesterday" if day == dt.date.today() - dt.timedelta(days=1) else day.strftime("%A %b %d"))
    if not checks:
        return f"{label}: no checks yet. {len(missed)} scheduled check(s) missed so far."
    scores = [c["score"] for c in checks]
    last = checks[-1]
    low = min(checks, key=lambda c: c["score"])
    words = {"good": "good", "fair": "lower than usual", "low": "much lower than usual"}
    return (f"{label}: {len(checks)} checks, average {round(sum(scores) / len(scores))}. Latest at {_clock(last['ts'])} was "
            f"{words.get(last['level'], last['level'])} ({round(last['score'])}). Lowest was {round(low['score'])} at "
            f"{_clock(low['ts'])}, {_hm(low.get('minutes_since_dose'))}. {len(doses)} dose(s) logged, "
            f"{len(missed)} check(s) missed.")


def chat_reply(store, sender: str, text: str, role: str = "caregiver") -> str:
    """Rule-based answers from our data, with per-sender context (remembers which day you asked about)."""
    key = f"chat:{sender}"
    ctx = store.get_setting(key, {"turns": [], "day": None}) or {"turns": [], "day": None}
    t = text.lower().strip()
    today = dt.date.today()
    day = None
    if ASKS_ADVICE.search(t):
        reply = ("I can't give medication advice. Please ask the care team; I can tell you how the checks have looked "
                 "and when doses were logged.")
    else:
        if "yesterday" in t:
            day = today - dt.timedelta(days=1)
        elif "today" in t or "now" in t:
            day = today
        elif re.search(r"\b(and|what about|how about)\b", t) and ctx.get("day"):
            day = dt.date.fromisoformat(ctx["day"])  # follow-up like "and the afternoon?" keeps the day in context
        if re.search(r"\bmiss", t):
            d = day or today
            start = dt.datetime.combine(d, dt.time()).timestamp()
            m = analysis.missed_checks(store.checks(start, start + 86400), start, min(start + 86400, time.time()))
            reply = (f"{len(m)} missed on {'that day' if d != today else 'today'}: " + ", ".join(_clock(x['ts']) for x in m)) if m else "No missed checks."
            day = d
        elif re.search(r"\b(last|latest|recent)\b.*\bcheck\b|\bcheck\b.*\b(last|latest)\b", t):
            c = store.latest_check()
            reply = (f"Latest check {_clock(c['ts'])}: score {round(c['score'])}, {_hm(c.get('minutes_since_dose'))}."
                     if c else "No checks yet.")
        elif re.search(r"\b(dose|meds|medicine|pill)\b", t):
            d = store.last_dose_before(time.time())
            reply = f"Last dose logged at {_clock(d)} ({_hm((time.time() - d) / 60).replace(' after the last dose', ' ago')})." if d else "No dose logged today yet."
        elif re.search(r"\breport|appointment|follow", t):
            r = store.get_setting("latest_report") or {}
            acts = [a for a in store.actions(30) if a["kind"] in ("follow_up_requested", "report_sent")]
            reply = ("The visit report was generated " + (_clock(r["generated_at"]) if r else "not yet") + ". "
                     + (acts[0]["detail"].get("text", "") if acts else "No follow-up requested yet."))
        elif day or re.search(r"\b(how|doing|status|summary|update)\b", t):
            day = day or today
            reply = day_summary(store, day)
        else:
            reply = ("I can answer from TapTrack data: 'today', 'yesterday', 'last check', 'missed', 'last dose', "
                     "or 'report'.")
    reply, _ = report.guard(reply)
    ctx["turns"] = (ctx.get("turns", []) + [{"q": text, "a": reply, "at": time.time()}])[-10:]
    if day:
        ctx["day"] = day.isoformat()
    store.set_setting(key, ctx)
    return reply
