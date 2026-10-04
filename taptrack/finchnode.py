"""FinchNode patient record + medication schedule (https://finchnode.com/docs).

- Public demo API (no key): https://api.finchnode.com/demo/v1
- Sandbox/production: https://api.finchnode.com/api/v1 with `Authorization: Bearer $FINCHNODE_API_KEY`
- Main route: GET /users/{subject}/records?categories=demographics,medications,conditions

FinchNode is read-only (patient-directed record access; no POST for clinical data, verified
2026-10-03: POST /fhir/Observation -> 404). So "write back" means each completed check is
turned into a FHIR R4 Observation and queued in the local outbox, ready for an EHR that
accepts writes. Nothing here pretends the write succeeded.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time

import httpx

from . import config

log = logging.getLogger("taptrack.finchnode")
CATEGORIES = "demographics,medications,conditions,allergies"
LEVODOPA = re.compile(r"levodopa|sinemet|rytary|carbidopa", re.I)
FREQ_TIMES = {  # frequency text -> dose clock times
    4: ["08:00", "12:00", "16:00", "20:00"], 3: ["08:00", "13:00", "18:00"], 5: ["07:00", "10:30", "14:00", "17:30", "21:00"],
    2: ["08:00", "20:00"], 6: ["07:00", "10:00", "13:00", "16:00", "19:00", "22:00"],
}
WORDS = {"once": 1, "twice": 2, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _headers():
    return {"Authorization": f"Bearer {config.FINCHNODE_API_KEY}"} if config.FINCHNODE_API_KEY else {}


PUBLIC_DEMO = "https://api.finchnode.com/demo/v1"
DEMO_SUBJECT = "patient-demo-polypharmacy"


def resolve_subject(timeout: float = 10.0) -> tuple[str, str, str]:
    """(base_url, subject, mode). With a sandbox key and no FINCHNODE_PATIENT_ID, use the first consented
    sandbox user; if there is none yet, fall back to the public demo record and say so."""
    base = config.FINCHNODE_BASE_URL.rstrip("/")
    explicit = config.env("FINCHNODE_PATIENT_ID")
    if not config.FINCHNODE_API_KEY:
        return PUBLIC_DEMO, explicit or DEMO_SUBJECT, "public demo"
    if explicit:
        return base, explicit, "sandbox"
    r = httpx.get(f"{base}/users", headers=_headers(), timeout=timeout)
    r.raise_for_status()
    users = r.json().get("data", [])
    if users:
        u = users[0]
        return base, u.get("subject") or u.get("id"), "sandbox"
    log.warning("FinchNode sandbox has no consented users yet; using the public demo record")
    return PUBLIC_DEMO, DEMO_SUBJECT, "public demo (sandbox has no consented user yet)"


def fetch_record(timeout: float = 10.0) -> tuple[dict, str, str]:
    base, subject, mode = resolve_subject(timeout)
    headers = _headers() if base != PUBLIC_DEMO else {}
    r = httpx.get(f"{base}/users/{subject}/records", params={"categories": CATEGORIES}, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json(), subject, mode


def doses_per_day(text: str) -> int | None:
    t = (text or "").lower()
    m = re.search(r"(\d+)\s*(?:x|times)\s*(?:a|per)?\s*day", t) or re.search(r"q(\d+)h", t)
    if m:
        n = int(m.group(1))
        return 24 // n if "q" in m.group(0) else n
    for w, n in WORDS.items():
        if re.search(rf"\b{w}\b.*\b(daily|a day|per day)\b", t):
            return n
    if "qid" in t:
        return 4
    if "tid" in t:
        return 3
    return None


def summarize(record: dict) -> dict:
    """Pull out what TapTrack needs: who, conditions, meds, and a levodopa schedule if present."""
    data = record.get("data", {})
    demo = data.get("demographics") or {}
    if isinstance(demo, list):
        demo = demo[0] if demo else {}
    birth = demo.get("birthDate")
    age = None
    if birth:
        b = dt.date.fromisoformat(birth[:10])
        today = dt.date.today()
        age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    meds = [m for m in data.get("medications", []) if (m.get("status") or "active") == "active"]
    levo = next((m for m in meds if LEVODOPA.search(m.get("name", ""))), None)
    schedule, schedule_source = list(config.DOSE_TIMES), "TapTrack configuration"
    if levo:
        n = doses_per_day(f"{levo.get('frequency') or ''} {levo.get('dosage') or ''}")
        if n in FREQ_TIMES:
            schedule, schedule_source = FREQ_TIMES[n], f"FinchNode order: {levo.get('name')}"
    return {
        "source": "finchnode", "mode": "public demo", "subject": None, "record_id": record.get("id"),
        "synthetic": record.get("synthetic", True),
        "name": (demo.get("name") or "").replace(" (synthetic)", ""), "age": age, "gender": demo.get("gender"),
        "conditions": [c.get("name") for c in data.get("conditions", []) if c.get("name")],
        "allergies": [a.get("name") or a.get("substance") for a in data.get("allergies", []) if (a.get("name") or a.get("substance"))],
        "medications": [{"name": m.get("name"), "frequency": m.get("frequency"), "dosage": m.get("dosage")} for m in meds],
        "levodopa_order": levo.get("name") if levo else None,
        "dose_times": schedule, "schedule_source": schedule_source,
        "fetched_at": time.time(),
    }


def load_patient(store) -> dict | None:
    """Fetch and cache the patient summary. Returns the cached copy if FinchNode is unreachable."""
    if not config.FINCHNODE_ENABLED:
        return None
    try:
        record, subject, mode = fetch_record()
        p = summarize(record)
        p.update(subject=subject, mode=mode)
        store.set_setting("patient", p)
        log.info("FinchNode record loaded: %s, %s meds, schedule from %s", p["name"], len(p["medications"]), p["schedule_source"])
        return p
    except Exception as ex:
        log.warning("FinchNode unavailable (%s); using cached record if any", ex)
        return store.get_setting("patient")


def observation(check: dict) -> dict:
    """A completed check as a FHIR R4 Observation (custom code; composite + per-test components)."""
    ts = dt.datetime.fromtimestamp(check["ts"], dt.timezone.utc).isoformat()
    comps = [{"code": {"text": f"{k} sub-score"}, "valueQuantity": {"value": round(v, 1), "unit": "score"}}
             for k, v in (check.get("tests") or {}).items()]
    if check.get("minutes_since_dose") is not None:
        comps.append({"code": {"text": "minutes since last levodopa dose"},
                      "valueQuantity": {"value": check["minutes_since_dose"], "unit": "min"}})
    return {
        "resourceType": "Observation", "status": "final" if check.get("complete", True) else "preliminary",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "exam"}]}],
        "code": {"text": "TapTrack PD composite motor score (wrist check)"},
        "subject": {"reference": f"Patient/{(config.env('FINCHNODE_PATIENT_ID') or 'taptrack-patient')}"},
        "effectiveDateTime": ts,
        "valueQuantity": {"value": check.get("score"), "unit": "score (0-100, 85 = personal baseline)"},
        "component": comps,
        "note": [{"text": "Decision support only. Not a diagnostic device."}],
    }


def queue_writeback(store, check: dict):
    store.add_outbox("fhir_observation", {
        "target": f"FinchNode {(store.get_setting('patient') or {}).get('subject', '')}",
        "reason": "FinchNode API is read-only; queued for an EHR that accepts writes",
        "resource": observation(check)}, status="queued")
