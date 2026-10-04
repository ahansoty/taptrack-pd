"""Composite 0-100 score vs the user's own baseline.

Each metric becomes a z-score in its "good" direction, mapped to a sub-score:
    sub = clip(85 + 15 * z, 0, 100)
so matching baseline = 85, one baseline-SD better = 100, one SD worse = 70.
Tests are weighted and missing tests are re-weighted away.
"""
from __future__ import annotations

import numpy as np

# metric key: (test, field, direction(+1 higher is better), weight within test, sd floor)
METRICS = {
    "flip_rate": ("flip", "flips_per_s", +1, 0.5, 0.3),
    "flip_amp": ("flip", "amplitude_g", +1, 0.25, 0.15),
    "flip_dec": ("flip", "amp_decrement_pct", -1, 0.25, 10.0),
    "tremor_rms": ("tremor", "rms_vec_mg", -1, 1.0, 8.0),
    "tap_rate": ("taps", "taps_per_s", +1, 0.5, 0.4),
    "tap_cv": ("taps", "iti_cv", -1, 0.3, 0.05),
    "tap_dec": ("taps", "rate_decrement_pct", -1, 0.2, 10.0),
    "voice_db": ("voice", "loudness_dbfs", +1, 0.6, 2.0),
    "voice_cv": ("voice", "stability_cv", -1, 0.4, 0.05),
}
TEST_WEIGHTS = {"flip": 0.3, "taps": 0.3, "tremor": 0.2, "voice": 0.2}
TEST_LABELS = {"flip": "Hand flipping", "tremor": "Tremor (hold still)", "taps": "Alternating taps", "voice": "Voice"}

# Default baseline (mean, sd) used until the user has their own. Values are in the
# device's units (see HARDWARE_NOTES.md) for a person in a good "on" state.
DEFAULT_BASELINE = {
    "flip_rate": (3.6, 0.5),
    "flip_amp": (1.6, 0.25),
    "flip_dec": (5.0, 10.0),
    "tremor_rms": (25.0, 10.0),
    "tap_rate": (4.2, 0.5),
    "tap_cv": (0.15, 0.05),
    "tap_dec": (5.0, 10.0),
    "voice_db": (-20.0, 3.0),
    "voice_cv": (0.15, 0.05),
}

GREEN_MIN, YELLOW_MIN = 70, 50


def extract(results: dict) -> dict:
    """results = {"flip": {...}, "tremor": {...}, ...} -> flat {metric_key: value}."""
    out = {}
    for key, (test, field, *_rest) in METRICS.items():
        r = results.get(test) or {}
        v = r.get(field)
        if r.get("valid", True) and v is not None:
            out[key] = float(v)
    return out


def baseline_from(history: list[dict]) -> dict:
    """Build a personal baseline (mean, sd) from a list of flat metric dicts."""
    base = {}
    for key, (_t, _f, _d, _w, floor) in METRICS.items():
        vals = [h[key] for h in history if h.get(key) is not None]
        if len(vals) >= 3:
            base[key] = (float(np.mean(vals)), max(float(np.std(vals, ddof=1)), floor))
        else:
            base[key] = DEFAULT_BASELINE[key]
    return base


def subscore(key: str, value: float, baseline: dict) -> float:
    _t, _f, direction, _w, floor = METRICS[key]
    mean, sd = baseline.get(key, DEFAULT_BASELINE[key])
    z = direction * (value - mean) / max(sd, floor)
    return float(np.clip(85 + 15 * z, 0, 100))


def score(results: dict, baseline: dict | None = None) -> dict:
    baseline = baseline or DEFAULT_BASELINE
    flat = extract(results)
    tests = {}
    for test in TEST_WEIGHTS:
        parts = [(METRICS[k][3], subscore(k, v, baseline)) for k, v in flat.items() if METRICS[k][0] == test]
        if parts:
            w = sum(p[0] for p in parts)
            tests[test] = round(sum(p[0] * p[1] for p in parts) / w, 1)
    if not tests:
        return {"score": None, "tests": {}, "metrics": flat, "level": "none"}
    w = sum(TEST_WEIGHTS[t] for t in tests)
    composite = round(sum(TEST_WEIGHTS[t] * s for t, s in tests.items()) / w)
    return {"score": int(composite), "tests": tests, "metrics": flat, "level": level(composite)}


def level(s: float | None) -> str:
    if s is None:
        return "none"
    return "good" if s >= GREEN_MIN else "fair" if s >= YELLOW_MIN else "low"


LED_RGB = {"good": (0, 80, 0), "fair": (90, 60, 0), "low": (90, 0, 0), "none": (0, 0, 40)}
