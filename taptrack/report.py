"""Visit report: a one-page neurologist report and a plain-language patient summary.

Gemini writes it when GEMINI_API_KEY is set; otherwise a deterministic template does.
Either way the text describes PATTERNS ONLY. A guard removes any sentence that reads as
medication advice (dose/timing changes), because this is decision support, not treatment.
"""
from __future__ import annotations

import json
import logging
import re
import time

from . import analysis, config

log = logging.getLogger("taptrack.report")

SYSTEM = """You write documentation for a neurologist from wrist-sensor data of a person with Parkinson's disease.
Rules you must follow:
- Describe observed patterns only: timing of motor scores relative to logged levodopa doses, time of day, 14-day trend,
  which tests change most, adherence to scheduled checks, data quality.
- NEVER recommend, suggest or imply any medication change: no dose, timing, frequency, drug, or "consider adjusting" language.
  The clinician decides treatment. You may say the pattern "may be worth reviewing at the visit".
- Use only the numbers provided. Do not invent values. Say when data are limited.
- Scores are 0-100 composites relative to the patient's own baseline (85 = at baseline).
- The patient summary is for the patient: warm, plain words, short sentences, reading level about grade 6, no jargon,
  no medication advice, encourage them to bring questions to their care team.
Return JSON: {"neurologist_report": markdown string (headings + bullets, about one page),
              "patient_summary": markdown string (under 180 words)}"""

_VERB = (r"increas|decreas|reduc|adjust|chang|shorten|lengthen|split|add|switch|titrat|doubl|skip|"
         r"mov|shift|consider (an? )?(extra|additional|earlier|later)")
_TARGET = r"dose|doses|dosing|dosage|levodopa|carbidopa|medication|medicine|pill|tablet|interval|regimen|\d+\s?mg"
ADVICE = re.compile(
    rf"\b({_VERB})(e|es|ed|ing|s|ion|ions|tion|ping|ped)?\b[^.\n]{{0,60}}\b({_TARGET})\b"
    rf"|\b({_TARGET})\b[^.\n]{{0,40}}\b(should|could|needs? to|ought to|may need to)\b[^.\n]{{0,30}}\b({_VERB})(e|es|ed|ing|s|ion|ions|tion|ping|ped)?\b"
    r"|\b(lower|raise)\s+(the|your|his|her)\s+(dose|dosage)\b", re.I)
# safety statements that mention changes only to forbid them are kept
SAFE = re.compile(r"\b(do not|don't|never|without (first )?(talking|speaking|checking))\b", re.I)
FOOTER = "_Decision support for clinicians. Not a diagnostic device. Patterns only; no treatment recommendations._"


def guard(text: str) -> tuple[str, int]:
    """Drop sentences/bullets that read as medication advice. Returns (text, n_removed)."""
    removed = 0
    out_lines = []
    for line in text.splitlines():
        parts = re.split(r"(?<=[.!?])\s+", line)
        kept = [p for p in parts if not ADVICE.search(p) or SAFE.search(p)]
        removed += len(parts) - len(kept)
        if parts and not kept and line.strip().startswith(("-", "*")):
            continue
        out_lines.append(" ".join(kept) if kept else ("" if line.strip() else line))
    return "\n".join(out_lines).strip(), removed


def _facts(store) -> dict:
    s = analysis.summary(store)
    p = store.get_setting("patient") or {}
    s["patient_record"] = {k: p.get(k) for k in ("name", "age", "gender", "conditions", "medications",
                                                 "levodopa_order", "dose_times", "schedule_source", "mode")} if p else None
    return s


def _fmt_h(minutes):
    return f"{minutes / 60:.1f} h" if minutes is not None else "n/a"


def template(f: dict) -> dict:
    wo, tr = f["wearing_off"], f["trend"]
    curve = [c for c in f["curve_by_time_since_dose"] if c["mean"] is not None]
    best = max(curve, key=lambda c: c["mean"]) if curve else None
    worst = min(curve, key=lambda c: c["mean"]) if curve else None
    tod = [t for t in f["time_of_day"] if t["mean"] is not None]
    low_hours = sorted(tod, key=lambda t: t["mean"])[:3]
    tests = sorted(((k, v) for k, v in f["tests"].items() if v["peak"] is not None and v["late"] is not None),
                   key=lambda kv: kv[1]["peak"] - kv[1]["late"], reverse=True)
    rec = f.get("patient_record") or {}
    who = f"{rec.get('name') or f['patient_name']}" + (f", {rec['age']} y" if rec.get("age") else "")
    lines = [
        f"# TapTrack PD visit report: {who}",
        f"**Period:** {f['period']['from']} to {f['period']['to']} ({f['period']['days']} days). "
        f"**Checks:** {f['n_checks']} completed, {f['n_missed_checks']} scheduled checks missed. "
        f"**Doses logged:** {f['n_doses_logged']} (schedule {', '.join(f['dose_schedule'])}"
        + (f"; source: {rec.get('schedule_source')}" if rec else "") + ").",
        "",
        "## Wearing-off pattern",
    ]
    if wo.get("detected"):
        lines += [
            f"- Scores peak at **{wo['peak_score']}** about 1 to 2.5 h after a logged dose and fall to **{wo['late_score']}** "
            f"3 to 4 h after a dose (a drop of {wo['drop_points']} points).",
            f"- On average the decline begins about **{_fmt_h(wo.get('onset_minutes'))}** after a dose and continues until the next dose.",
        ]
    else:
        lines.append(f"- No consistent wearing-off pattern detected ({wo.get('reason', 'peak and late scores are similar')}).")
    if best and worst:
        lines.append(f"- Highest mean score at {best['bin']} after a dose ({best['mean']}); lowest at {worst['bin']} ({worst['mean']}).")
    lines += ["", "## Time of day"]
    if low_hours:
        lines.append("- Lowest mean scores by clock hour: " + ", ".join(f"{t['hour']}:00 ({t['mean']})" for t in low_hours) + ".")
    lines += ["", "## Which tests change most"]
    for k, v in tests[:4]:
        lines.append(f"- {v['label']}: {v['peak']} at peak vs {v['late']} late (difference {round(v['peak'] - v['late'], 1)}).")
    lines += ["", "## 14-day trend",
              f"- Daily mean score changes by {tr['slope_per_day']:+.2f} points per day over the period "
              f"({tr['means'][0] if tr['means'] else 'n/a'} on day 1, {tr['means'][-1] if tr['means'] else 'n/a'} most recently)."]
    if f.get("passive_tremor_mean_mg") is not None:
        lines.append(f"- Passive tremor sampling between checks: mean {f['passive_tremor_mean_mg']} mg RMS.")
    lines += ["", "## Data quality",
              f"- {f['n_missed_checks']} scheduled checks were missed; recent misses: "
              + (", ".join(f"{m['date']} {m['slot']}" for m in f["missed_recent"][-5:]) or "none") + ".",
              "- Scores are relative to this patient's own ON-state baseline (85 = baseline)."]
    if rec.get("conditions"):
        lines += ["", "## Record context (FinchNode)",
                  f"- Conditions on record: {', '.join(rec['conditions'][:8])}.",
                  f"- Active medications on record: {', '.join(m['name'] for m in (rec.get('medications') or [])[:10]) or 'none listed'}."]
    lines += ["", "These patterns may be worth reviewing at the visit.", "", FOOTER]
    patient = [
        "## Your last two weeks",
        f"You did {f['n_checks']} wrist checks. Thank you, that helps your care team a lot.",
    ]
    if wo.get("detected"):
        patient.append(f"Your movement scores were best about 1 to 2 hours after your medicine, and lower about "
                       f"{_fmt_h(wo.get('onset_minutes'))} later, before your next dose.")
    patient += [f"You missed {f['n_missed_checks']} checks. That is okay, try to do the next one when the watch asks.",
                "Please bring any questions about this to your care team. Do not change how you take your medicine "
                "without talking to them first.", "", FOOTER]
    return {"neurologist_report": "\n".join(lines), "patient_summary": "\n".join(patient)}


def gemini(f: dict) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents="Patient data (JSON):\n" + json.dumps(f, default=float),
        config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.2,
                                           response_mime_type="application/json"))
    data = json.loads(resp.text)
    return {"neurologist_report": data["neurologist_report"], "patient_summary": data["patient_summary"]}


def generate(store) -> dict:
    f = _facts(store)
    engine = "template"
    if config.GEMINI_API_KEY:
        try:
            out = gemini(f)
            engine = f"Gemini ({config.GEMINI_MODEL})"
        except Exception as ex:
            log.warning("Gemini failed (%s); using template", ex)
            out = template(f)
            engine = "template (Gemini unavailable)"
    else:
        out = template(f)
    removed = 0
    for k in ("neurologist_report", "patient_summary"):
        out[k], n = guard(out[k])
        removed += n
        if FOOTER not in out[k]:
            out[k] += "\n\n" + FOOTER
    report = {**out, "engine": engine, "generated_at": time.time(), "advice_sentences_removed": removed,
              "facts": {k: f[k] for k in ("period", "n_checks", "n_missed_checks", "wearing_off")}}
    store.set_setting("latest_report", report)
    return report
