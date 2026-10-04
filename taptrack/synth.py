"""Synthetic patient on levodopa 4x/day with wearing-off, used for the 14-day dataset,
the simulated device, and DEMO_MODE replay.

Model: each dose gives benefit rise(h) * decay(h): onset ~30-60 min after the dose,
plateau, then decline from ~3 h, so the patient dips ("wears off") before the next dose.
Over 14 days the benefit window shortens a little and the ON level drifts down slightly.
"""
from __future__ import annotations

import datetime as dt
import math
import time

import numpy as np

from . import config, scoring

ON = {k: v[0] for k, v in scoring.DEFAULT_BASELINE.items()}
OFF = {"flip_rate": 2.0, "flip_amp": 1.0, "flip_dec": 35.0, "tremor_rms": 95.0, "tap_rate": 2.3,
       "tap_cv": 0.38, "tap_dec": 32.0, "voice_db": -27.0, "voice_cv": 0.38}
NOISE_FRAC = 0.45  # noise sd as a fraction of the baseline sd


def benefit(hours_since_dose: float, day_frac: float = 0.0) -> float:
    """0 = fully OFF, 1 = fully ON for one dose. day_frac in [0,1] over the 14 days."""
    if hours_since_dose is None or hours_since_dose < 0:
        return 0.0
    onset = 0.6 + 0.1 * day_frac          # hours to half effect (~36-42 min)
    wear = 3.35 - 0.45 * day_frac          # hours to half wear-off (3.35 h -> 2.9 h)
    rise = 1 / (1 + math.exp(-(hours_since_dose - onset) / 0.13))
    decay = 1 / (1 + math.exp((hours_since_dose - wear) / 0.28))
    return rise * decay


def state_at(ts: float, dose_ts: list[float], day_frac: float = 0.0) -> float:
    """Combined motor state from the last two doses (overlap near dose time)."""
    prior = [d for d in dose_ts if d <= ts][-2:]
    b = sum(benefit((ts - d) / 3600, day_frac) for d in prior)
    level = 1.0 - 0.08 * day_frac         # slight downward trend in peak ON
    return float(min(1.0, b) * level)


def metrics_for_state(state: float, rng: np.random.Generator) -> dict:
    out = {}
    for k in ON:
        mean = OFF[k] + (ON[k] - OFF[k]) * state
        sd = scoring.DEFAULT_BASELINE[k][1] * NOISE_FRAC
        out[k] = float(mean + sd * rng.standard_normal())
    out["flip_rate"] = max(out["flip_rate"], 0.5)
    out["tap_rate"] = max(out["tap_rate"], 0.5)
    out["tremor_rms"] = max(out["tremor_rms"], 5.0)
    out["tap_cv"] = max(out["tap_cv"], 0.03)
    out["voice_cv"] = max(out["voice_cv"], 0.03)
    return out


def results_from_metrics(m: dict, dominant_hz: float | None = None) -> dict:
    """Shape flat metrics like the per-test results produced by the device."""
    return {
        "flip": {"valid": True, "flips_per_s": round(m["flip_rate"], 3), "amplitude_g": round(m["flip_amp"], 3),
                 "amp_decrement_pct": round(m["flip_dec"], 1), "flips": int(m["flip_rate"] * 10)},
        "tremor": {"valid": True, "rms_vec_mg": round(m["tremor_rms"], 2), "rms_mg": round(m["tremor_rms"] * 0.7, 2),
                   "dominant_hz": dominant_hz, "freq_enabled": dominant_hz is not None},
        "taps": {"valid": True, "taps_per_s": round(m["tap_rate"], 3), "iti_cv": round(m["tap_cv"], 3),
                 "rate_decrement_pct": round(m["tap_dec"], 1), "taps": int(m["tap_rate"] * 10), "errors": 0},
        "voice": {"valid": True, "loudness_dbfs": round(m["voice_db"], 2), "stability_cv": round(m["voice_cv"], 3),
                  "voiced_s": 4.6},
    }


def _at(day: dt.date, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m)).timestamp()


def generate(days: int = 14, end_ts: float | None = None, seed: int = 7) -> dict:
    """Return {'doses': [...], 'checks': [...], 'passive': [...], 'baseline': {...}}.
    Ends at end_ts (default now), so 'today' is partially filled."""
    rng = np.random.default_rng(seed)
    end_ts = end_ts or time.time()
    today = dt.date.fromtimestamp(end_ts)
    first = today - dt.timedelta(days=days - 1)
    doses, checks, passive = [], [], []
    # a lunchtime cluster of missed checks one afternoon, plus ~7% random misses
    missed_cluster = (first + dt.timedelta(days=days - 5), {"12:45", "14:00", "15:15"})
    for i in range(days):
        day = first + dt.timedelta(days=i)
        day_frac = i / max(days - 1, 1)
        for j, hhmm in enumerate(config.DOSE_TIMES):
            jitter = rng.normal(0, 8) * 60
            if i == days - 8 and j == 2:
                jitter = 50 * 60  # one late afternoon dose
            doses.append(_at(day, hhmm) + jitter)
    doses.sort()
    for i in range(days):
        day = first + dt.timedelta(days=i)
        day_frac = i / max(days - 1, 1)
        # active checks
        for hhmm in config.CHECK_TIMES:
            ts = _at(day, hhmm) + rng.normal(0, 12) * 60
            if ts > end_ts:
                continue
            if (day == missed_cluster[0] and hhmm in missed_cluster[1]) or rng.random() < 0.07:
                continue
            s = state_at(ts, doses, day_frac)
            m = metrics_for_state(s, rng)
            dom = round(float(rng.normal(5.2, 0.3)), 2) if m["tremor_rms"] > 45 else None
            prior = [d for d in doses if d <= ts]
            checks.append({"ts": ts, "results": results_from_metrics(m, dom), "state": s,
                           "minutes_since_dose": round((ts - prior[-1]) / 60, 1) if prior else None})
        # passive tremor every 15 min, 07:00-22:00
        t = _at(day, "07:00")
        while t < _at(day, "22:00") and t <= end_ts:
            s = state_at(t, doses, day_frac)
            rms = max(4.0, OFF["tremor_rms"] + (ON["tremor_rms"] - OFF["tremor_rms"]) * s + rng.normal(0, 6))
            prior = [d for d in doses if d <= t]
            passive.append({"ts": t, "rms_mg": round(rms, 1),
                            "dominant_hz": round(float(rng.normal(5.2, 0.3)), 2) if rms > 45 else None,
                            "minutes_since_dose": round((t - prior[-1]) / 60, 1) if prior else None})
            t += 15 * 60 + rng.normal(0, 60)
    doses = [d for d in doses if d <= end_ts]
    # personal baseline from early-days peak-ON checks (60-150 min post dose, days 1-4)
    early = [c for c in checks if c["ts"] < _at(first + dt.timedelta(days=4), "00:00")
             and c["minutes_since_dose"] and 60 <= c["minutes_since_dose"] <= 150]
    baseline = scoring.baseline_from([scoring.extract(c["results"]) for c in early])
    return {"doses": doses, "checks": checks, "passive": passive, "baseline": baseline}


def load_into(store, days: int = 14, end_ts: float | None = None, seed: int = 7) -> dict:
    """Replace synthetic rows in storage and set the personal baseline. Returns summary stats."""
    data = generate(days, end_ts, seed)
    store.clear_source("synthetic")
    for d in data["doses"]:
        store.add_dose(d, source="synthetic")
    base = data["baseline"]
    store.set_setting("baseline", {k: list(v) for k, v in base.items()})
    scores = []
    for c in data["checks"]:
        s = scoring.score(c["results"], base)
        scores.append((c, s["score"]))
        store.add_check(c["ts"], s["score"], s["level"], s["tests"], s["metrics"], c["results"],
                        source="synthetic", minutes_since_dose=c["minutes_since_dose"])
    for p in data["passive"]:
        store.add_passive(p["ts"], p["rms_mg"], p["dominant_hz"], source="synthetic",
                          minutes_since_dose=p["minutes_since_dose"])
    return summarize(scores, data)


def summarize(scores, data) -> dict:
    arr = np.array([s for _, s in scores], dtype=float)
    mins = np.array([c["minutes_since_dose"] or 0 for c, _ in scores])
    bins = {}
    for lo, hi in [(0, 30), (30, 60), (60, 120), (120, 180), (180, 240), (240, 600)]:
        sel = (mins >= lo) & (mins < hi)
        if sel.any():
            bins[f"{lo}-{hi} min"] = round(float(arr[sel].mean()), 1)
    n_days = len({dt.date.fromtimestamp(c["ts"]) for c, _ in scores})
    expected = n_days * len(config.CHECK_TIMES)
    first3 = arr[: len(arr) // 4].mean()
    last3 = arr[-len(arr) // 4:].mean()
    return {"doses": len(data["doses"]), "checks": len(scores), "passive_samples": len(data["passive"]),
            "approx_missed": max(expected - len(scores), 0), "score_mean": round(float(arr.mean()), 1),
            "score_by_time_since_dose": bins, "first_quarter_mean": round(float(first3), 1),
            "last_quarter_mean": round(float(last3), 1)}
