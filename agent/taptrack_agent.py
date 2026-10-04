"""TapTrack PD care-team agent (Fetch.ai uAgents, Agentverse mailbox, ASI:One chat protocol).

Two agents run in one Bureau:
- taptrack-care  (mailbox, registered on Agentverse, discoverable in ASI:One): watches the TapTrack API and
  decides what to do:
    * red score on a wrist check      -> iMessage alert to the caregiver (Photon)
    * scheduled check missed          -> iMessage reminder to the patient (Photon)
    * wearing-off pattern in 14 days  -> generate the visit report, send it to the clinic agent with a
                                         follow-up request, then tell the caregiver (Photon)
  It also answers ASI:One chat ("how is she doing today?", "send the visit report", "book a follow-up").
- taptrack-clinic (local): stands in for the neurology clinic's scheduling desk; receives the report and
  offers the next open follow-up slot. Agent-to-agent messaging = multi-agent orchestration.

Run:  agent/.venv/Scripts/python agent/taptrack_agent.py   (TapTrack server must be running)
Then open the Inspector link printed in the log -> Connect -> Mailbox (one time).
"""
from __future__ import annotations

import datetime as dt
import os
import secrets
import time
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from uagents import Agent, Bureau, Context, Model, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")
import logging  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)


def env(k, d=""):
    return (os.getenv(k) or "").strip() or d


API = env("TAPTRACK_URL", f"http://127.0.0.1:{env('PORT', '8000')}")
POLL_S = float(env("AGENT_POLL_S", "3"))
DEMO = env("DEMO_MODE", "false").lower() in ("1", "true", "yes")
DEMO_ALERT_ALL = DEMO and env("DEMO_ALERT_ALL_CHECKS", "true").lower() != "false"
DOCTOR = env("NEUROLOGIST_NAME", "Dr. Patel (Movement Disorders Clinic)")
# one follow-up request per pattern per week; 30 min in DEMO_MODE so a fresh demo shows the full flow
FOLLOWUP_COOLDOWN_S = float(env("FOLLOWUP_COOLDOWN_S", str(1800 if DEMO else 7 * 86400)))


def seed(name: str) -> str:
    """Stable private seed: AGENT_SEED from .env, else generated once into agent/.seed (git-ignored)."""
    s = env("AGENT_SEED")
    if not s:
        f = HERE / ".seed"
        if not f.exists():
            f.write_text(secrets.token_hex(24))
        s = f.read_text().strip()
    return f"{s}-{name}"


care = Agent(name="taptrack-care", seed=seed("care"), port=int(env("AGENT_PORT", "8001")), mailbox=True,
             publish_agent_details=True, readme_path=str(HERE / "README.md"))
clinic = Agent(name="taptrack-clinic", seed=seed("clinic"))


# ------------------------------------------------------------------ agent-to-agent models
class FollowUpRequest(Model):
    request_id: str
    patient_name: str
    reason: str
    report_summary: str
    within_days: int = 14


class FollowUpOffer(Model):
    request_id: str
    clinician: str
    slot_text: str
    slot_iso: str


# ------------------------------------------------------------------ TapTrack API helpers
async def api(method: str, path: str, **kw):
    async with httpx.AsyncClient(base_url=API, timeout=30) as c:
        r = await c.request(method, path, **kw)
        r.raise_for_status()
        return r.json()


async def action(kind: str, detail: dict):
    try:
        await api("POST", "/api/actions", json={"kind": kind, "detail": detail})
    except Exception:
        pass


async def notify(kind: str, **fields):
    try:
        return await api("POST", "/api/notify", json={"kind": kind, "source": "fetch.ai agent", **fields})
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


# ------------------------------------------------------------------ decisions
async def check_latest(ctx: Context):
    c = await api("GET", "/api/checks/latest")
    if not c or not c.get("id") or c.get("source") == "synthetic":
        return
    if ctx.storage.get("last_check_id") == c["id"]:
        return
    first_seen = ctx.storage.get("last_check_id") is None
    ctx.storage.set("last_check_id", c["id"])
    if first_seen and time.time() - c["ts"] > 120:
        return  # don't alert on an old check when the agent starts
    if c.get("level") == "low" or DEMO_ALERT_ALL:
        r = await notify("caregiver_alert", to="caregiver", check=c)
        ctx.logger.info(f"check {c['id']} level={c.get('level')} -> caregiver alert sent={r.get('ok')} {r.get('error') or ''}")


async def check_missed(ctx: Context):
    cg = await api("GET", "/api/caregiver")
    reminded = set(ctx.storage.get("reminded") or [])
    for slot in cg.get("missed_today", []):
        key = f"{slot['date']} {slot['slot']}"
        # only recent misses (within 90 min): a reminder about this morning's slot at 9 PM is noise
        if key in reminded or time.time() - slot["ts"] > 90 * 60:
            continue
        r = await notify("missed_reminder", to="patient", slot=slot)
        reminded.add(key)
        ctx.logger.info(f"missed {key} -> patient reminder sent={r.get('ok')} {r.get('error') or ''}")
    ctx.storage.set("reminded", sorted(reminded)[-50:])


async def check_wearing_off(ctx: Context, force: bool = False) -> str:
    s = await api("GET", "/api/summary")
    wo = s["wearing_off"]
    last = ctx.storage.get("followup_requested_at") or 0
    if not force and (not wo.get("detected") or time.time() - last < FOLLOWUP_COOLDOWN_S):
        return "Wearing-off pattern present; a follow-up was already requested recently." if wo.get("detected") else "No wearing-off pattern detected."
    rep = await api("POST", "/api/report")
    summary = (f"Scores peak at {wo.get('peak_score')} 1-2.5 h after doses and fall to {wo.get('late_score')} at 3-4 h "
               f"(-{wo.get('drop_points')} pts); decline starts ~{(wo.get('onset_minutes') or 0) / 60:.1f} h after a dose.")
    rid = str(uuid4())
    ctx.storage.set("followup_requested_at", time.time())
    ctx.storage.set("pending_request", {"id": rid, "summary": summary, "onset": wo.get("onset_minutes")})
    await action("report_to_neurologist", {"text": f"Visit report ({rep.get('engine')}) sent to {DOCTOR} via the clinic agent.", "to": DOCTOR})
    await ctx.send(clinic.address, FollowUpRequest(request_id=rid, patient_name=s.get("patient_name", "patient"),
                                                   reason="Wearing-off pattern on wrist checks", report_summary=summary))
    ctx.logger.info(f"wearing-off -> report sent, follow-up requested ({rid[:8]})")
    return f"Sent the 14-day visit report to {DOCTOR} and requested a follow-up. {summary}"


@care.on_interval(period=POLL_S)
async def watch(ctx: Context):
    try:
        await api("POST", "/api/agent/heartbeat", json={"address": care.address, "name": care.name})
        await check_latest(ctx)
        n = (ctx.storage.get("ticks") or 0) + 1
        ctx.storage.set("ticks", n)
        if n % max(1, int(30 / POLL_S)) == 1:
            await check_missed(ctx)
        if n % max(1, int(120 / POLL_S)) == 1:
            await check_wearing_off(ctx)
    except httpx.HTTPError as ex:
        ctx.logger.warning(f"TapTrack API unreachable at {API}: {ex}")


@care.on_message(FollowUpOffer)
async def on_offer(ctx: Context, sender: str, offer: FollowUpOffer):
    pending = ctx.storage.get("pending_request") or {}
    await action("follow_up_requested", {"text": f"{offer.clinician} offered {offer.slot_text}.", "slot": offer.slot_iso})
    r = await notify("report_sent", to="caregiver", doctor=offer.clinician, appointment=offer.slot_text,
                     onset_minutes=pending.get("onset"))
    ctx.logger.info(f"follow-up offer {offer.slot_text} -> caregiver told sent={r.get('ok')}")


# ------------------------------------------------------------------ clinic agent
@clinic.on_message(FollowUpRequest)
async def on_request(ctx: Context, sender: str, req: FollowUpRequest):
    day = dt.date.today() + dt.timedelta(days=2)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    slot = dt.datetime.combine(day, dt.time(10, 30))
    ctx.logger.info(f"clinic received report for {req.patient_name}: {req.reason}")
    await ctx.send(sender, FollowUpOffer(request_id=req.request_id, clinician=DOCTOR,
                                         slot_text=slot.strftime("%a %b %d, %I:%M %p").replace(" 0", " "),
                                         slot_iso=slot.isoformat()))


# ------------------------------------------------------------------ ASI:One chat protocol
chat = Protocol(spec=chat_protocol_spec)


def text_msg(text: str) -> ChatMessage:
    return ChatMessage(timestamp=dt.datetime.now(dt.timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=text), EndSessionContent(type="end-session")])


async def answer(ctx: Context, sender: str, q: str) -> str:
    t = q.lower()
    try:
        if "report" in t or "neurolog" in t:
            return await check_wearing_off(ctx, force=True)
        if "follow" in t or "appointment" in t or "book" in t:
            return await check_wearing_off(ctx, force=True)
        if "remind" in t:
            cg = await api("GET", "/api/caregiver")
            if not cg.get("missed_today"):
                return "No missed checks today, so no reminder is needed."
            slot = cg["missed_today"][-1]
            r = await notify("missed_reminder", to="patient", slot=slot)
            return f"Reminder for the {slot['slot']} check {'sent by iMessage' if r.get('ok') else 'could not be sent: ' + str(r.get('error'))}."
        if "test message" in t or "text the caregiver" in t:
            r = await api("POST", "/api/notify/test")
            return "Test iMessage sent to the caregiver." if r.get("ok") else f"Could not send: {r.get('error')}"
        r = await api("POST", "/api/chat", json={"from": f"asi1:{sender[-8:]}", "role": "asi1", "text": q})
        return r["reply"] + "\n\n(Decision support only. Not a diagnostic device.)"
    except httpx.HTTPError as ex:
        return f"TapTrack is unreachable right now ({ex.__class__.__name__}). Please try again shortly."


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=dt.datetime.now(dt.timezone.utc), acknowledged_msg_id=msg.msg_id))
    for item in msg.content:
        if isinstance(item, StartSessionContent):
            ctx.logger.info(f"session start {sender[:16]}")
        elif isinstance(item, TextContent):
            ctx.logger.info(f"ASI:One asked: {item.text[:80]}")
            await ctx.send(sender, text_msg(await answer(ctx, sender, item.text)))


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


care.include(chat, publish_manifest=True)

if __name__ == "__main__":
    port = int(env("AGENT_PORT", "8001"))
    print(f"taptrack-care   {care.address}")
    print(f"taptrack-clinic {clinic.address}")
    # Bureau doesn't log the inspector link; open it once, Connect -> Mailbox, to register on Agentverse
    print(f"Agent inspector: https://agentverse.ai/inspect/?uri=http%3A//127.0.0.1%3A{port}&address={care.address}", flush=True)
    bureau = Bureau(port=port)
    bureau.add(care)
    bureau.add(clinic)
    bureau.run()
