"""Pattern analysis shared by the dashboard, the visit report and the Fetch.ai agent.
Describes patterns only; never recommends medication changes."""
from __future__ import annotations

import datetime as dt
import time

import numpy as np

from . import config, scoring

BINS = [(0, 30), (30, 60), (60, 90), (90, 120), (120, 150), (150, 180), (180, 210), (210, 240), (240, 300)]
BIN_LABELS = ["0-0.5h", "0.5-1h", "1-1.5h", "1.5-2h", "2-2.5h", "2.5-3h", "3-3.5h", "3.5-4h", "4h+"]
MISS_WINDOW_MIN = 45


def day_start(ts: float | None = None) -> float:
    d = dt.date.fromtimestamp(ts or time.time())
    return dt.datetime.combine(d, dt.time()).timestamp()


def _slot_ts(day: dt.date, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m)).timestamp()


def missed_checks(checks: list[dict], since: float, until: float | None = None) -> list[dict]:
    """Expected check windows with no check within +/-45 min."""
    until = until or time.time()
    times = np.array([c["ts"] for c in checks]) if checks else np.zeros(0)
    out = []
    day = dt.date.fromtimestamp(since)
    while day <= dt.date.fromtimestamp(until):
        for hhmm in config.CHECK_TIMES:
            ts = _slot_ts(day, hhmm)
            if ts < since or ts + MISS_WINDOW_MIN * 60 > until:
                continue
            if not np.any(np.abs(times - ts) <= MISS_WINDOW_MIN * 60):
                out.append({"ts": ts, "slot": hhmm, "date": day.isoformat()})
        day += dt.timedelta(days=1)
    return out


def bin_index(minutes: float | None) -> int | None:
    if minutes is None:
        return None
    for i, (lo, hi) in enumerate(BINS):
        if lo <= minutes < hi:
            return i
    return len(BINS) - 1 if minutes >= BINS[-1][0] and minutes < 12 * 60 else None


def heatmap(checks: list[dict], days: int = 14, now: float | None = None) -> dict:
    """Rows = days (oldest first), cols = time since last dose bins. Cell = mean score or None."""
    now = now or time.time()
    first = dt.date.fromtimestamp(now) - dt.timedelta(days=days - 1)
    rows = []
    for i in range(days):
        day = first + dt.timedelta(days=i)
        cells = [[] for _ in BINS]
        for c in checks:
            if dt.date.fromtimestamp(c["ts"]) == day and c.get("score") is not None:
                b = bin_index(c.get("minutes_since_dose"))
                if b is not None:
                    cells[b].append(c["score"])
        rows.append({"date": day.isoformat(), "label": day.strftime("%a %d"),
                     "cells": [round(float(np.mean(v))) if v else None for v in cells],
                     "n": [len(v) for v in cells]})
    return {"bins": BIN_LABELS, "rows": rows}


def curve_by_bin(checks: list[dict]) -> list[dict]:
    out = []
    for i, label in enumerate(BIN_LABELS):
        v = [c["score"] for c in checks if c.get("score") is not None and bin_index(c.get("minutes_since_dose")) == i]
        out.append({"bin": label, "mean": round(float(np.mean(v)), 1) if v else None,
                    "sd": round(float(np.std(v)), 1) if len(v) > 1 else None, "n": len(v)})
    return out


def wearing_off(checks: list[dict]) -> dict:
    """Detect a wearing-off pattern: scores 3-4 h after a dose clearly below the 1-2.5 h peak.
    Returns onset (first bin after the peak where the mean drops >= 10 points)."""
    curve = curve_by_bin(checks)
    peak_bins = [c for c in curve[2:5] if c["mean"] is not None]
    late_bins = [c for c in curve[6:8] if c["mean"] is not None]
    if not peak_bins or not late_bins or sum(c["n"] for c in curve) < 12:
        return {"detected": False, "reason": "not enough data", "curve": curve}
    peak = max(c["mean"] for c in peak_bins)
    late = float(np.mean([c["mean"] for c in late_bins]))
    onset = None
    for i in range(3, len(curve)):
        c = curve[i]
        if c["mean"] is not None and c["mean"] <= peak - 10 and i >= 4:
            onset = BINS[i][0]
            break
    # how many dosing intervals (dose-to-next-dose) show the dip
    drop = round(peak - late, 1)
    return {"detected": drop >= 15, "peak_score": round(peak, 1), "late_score": round(late, 1),
            "drop_points": drop, "onset_minutes": onset, "curve": curve}


def daily_trend(checks: list[dict]) -> dict:
    by_day: dict[str, list] = {}
    for c in checks:
        if c.get("score") is not None:
            by_day.setdefault(dt.date.fromtimestamp(c["ts"]).isoformat(), []).append(c["score"])
    days = sorted(by_day)
    means = [float(np.mean(by_day[d])) for d in days]
    slope = float(np.polyfit(np.arange(len(means)), means, 1)[0]) if len(means) >= 3 else 0.0
    return {"days": days, "means": [round(m, 1) for m in means], "slope_per_day": round(slope, 2)}


def time_of_day_profile(checks: list[dict]) -> list[dict]:
    out = []
    for h in range(6, 23):
        v = [c["score"] for c in checks if c.get("score") is not None and dt.datetime.fromtimestamp(c["ts"]).hour == h]
        out.append({"hour": h, "mean": round(float(np.mean(v)), 1) if v else None, "n": len(v)})
    return out


def test_breakdown(checks: list[dict]) -> dict:
    """Per-test mean sub-score in peak (60-150 min) vs late (180-240 min) windows."""
    out = {}
    for test, label in scoring.TEST_LABELS.items():
        peak = [c["tests"][test] for c in checks if c.get("tests") and test in c["tests"]
                and c.get("minutes_since_dose") is not None and 60 <= c["minutes_since_dose"] < 150]
        late = [c["tests"][test] for c in checks if c.get("tests") and test in c["tests"]
                and c.get("minutes_since_dose") is not None and 180 <= c["minutes_since_dose"] < 240]
        out[test] = {"label": label, "peak": round(float(np.mean(peak)), 1) if peak else None,
                     "late": round(float(np.mean(late)), 1) if late else None}
    return out


def summary(store, days: int = 14) -> dict:
    """Everything the report and agent need, as plain numbers."""
    now = time.time()
    since = day_start(now) - (days - 1) * 86400
    checks = store.checks(since)
    doses = store.doses(since)
    missed = missed_checks(checks, since, now)
    wo = wearing_off(checks)
    return {
        "patient_id": config.PATIENT_ID,
        "patient_name": config.PATIENT_NAME,
        "period": {"from": dt.date.fromtimestamp(since).isoformat(), "to": dt.date.fromtimestamp(now).isoformat(),
                   "days": days},
        "dose_schedule": config.DOSE_TIMES,
        "n_checks": len(checks),
        "n_doses_logged": len(doses),
        "n_missed_checks": len(missed),
        "missed_recent": missed[-10:],
        "wearing_off": {k: v for k, v in wo.items() if k != "curve"},
        "curve_by_time_since_dose": wo["curve"],
        "time_of_day": time_of_day_profile(checks),
        "trend": daily_trend(checks),
        "tests": test_breakdown(checks),
        "passive_tremor_mean_mg": _passive_mean(store, since),
    }


def _passive_mean(store, since):
    p = store.passive(since)
    return round(float(np.mean([x["rms_mg"] for x in p])), 1) if p else None
