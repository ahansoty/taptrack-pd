"""Motor and voice metrics from FREE-WILi signals (numpy/scipy only, no I/O).

All accelerometer inputs are times in seconds (any clock, may be bursty/uneven) and an
(N, 3) array in g. Signals are resampled to a uniform grid before filtering because the
USB event stream arrives in bursts (see hardware/NOTES.md).
"""
from __future__ import annotations

import numpy as np
from scipy import signal

TREMOR_FREQ_MIN_RATE_HZ = 40.0
VOICE_ABS_FLOOR = 250.0  # raw mic units after DC removal


def measured_rate(t) -> float:
    t = np.asarray(t, dtype=float)
    if t.size < 2 or t[-1] <= t[0]:
        return 0.0
    return (t.size - 1) / (t[-1] - t[0])


def resample(t, x, fs: float):
    """Linear interpolation onto a uniform grid. x may be 1-D or (N, k)."""
    t = np.asarray(t, dtype=float)
    x = np.asarray(x, dtype=float)
    order = np.argsort(t, kind="stable")
    t, x = t[order], x[order]
    t, idx = np.unique(t, return_index=True)
    x = x[idx]
    n = int(np.floor((t[-1] - t[0]) * fs)) + 1
    tu = t[0] + np.arange(n) / fs
    if x.ndim == 1:
        return tu, np.interp(tu, t, x)
    return tu, np.column_stack([np.interp(tu, t, x[:, i]) for i in range(x.shape[1])])


def _lowpass(x, fs, cutoff, order=2):
    if fs <= 2.2 * cutoff:
        return x
    b, a = signal.butter(order, cutoff / (fs / 2), btype="low")
    return signal.filtfilt(b, a, x, axis=0) if len(x) > 3 * max(len(a), len(b)) else x


def _highpass(x, fs, cutoff, order=2):
    if fs <= 2.2 * cutoff:
        return signal.detrend(x, axis=0)
    b, a = signal.butter(order, cutoff / (fs / 2), btype="high")
    return signal.filtfilt(b, a, x, axis=0) if len(x) > 3 * max(len(a), len(b)) else signal.detrend(x, axis=0)


def _thirds_change(first: float, last: float) -> float:
    """Percent decrement from first third to last third (positive = got worse/smaller)."""
    if first <= 1e-9:
        return 0.0
    return float((first - last) / first * 100.0)


def _too_short(t, min_n=8):
    return len(t) < min_n or (t[-1] - t[0]) < 1.0


# --------------------------------------------------------------------------- hand flip
def hand_flip(t, xyz, fs: float = 50.0) -> dict:
    """Rapid pronation/supination. A 'flip' is one palm-up <-> palm-down transition,
    seen as a zero crossing of gravity on the axis that swings the most."""
    t = np.asarray(t, dtype=float)
    xyz = np.asarray(xyz, dtype=float)
    if _too_short(t):
        return {"valid": False, "reason": "too few samples"}
    rate = measured_rate(t)
    fs = min(fs, max(rate, 10.0))
    tu, a = resample(t, xyz, fs)
    a = _lowpass(a, fs, 6.0)
    axis = int(np.argmax(a.std(axis=0)))
    s = a[:, axis] - np.median(a[:, axis])
    peak = np.percentile(np.abs(s), 95)
    hyst = max(0.15, 0.25 * peak)

    # zero crossings with hysteresis: state flips only after passing +/-hyst
    state, crossings = 0, []
    for i, v in enumerate(s):
        if state <= 0 and v > hyst:
            if state < 0:
                crossings.append(i)
            state = 1
        elif state >= 0 and v < -hyst:
            if state > 0:
                crossings.append(i)
            state = -1
    duration = tu[-1] - tu[0]
    flips = len(crossings)
    # amplitude per half-cycle: peak-to-peak between consecutive crossings
    amps, times = [], []
    bounds = [0] + crossings + [len(s) - 1]
    for i0, i1 in zip(bounds[:-1], bounds[1:]):
        if i1 - i0 >= 2:
            seg = s[i0:i1]
            amps.append(float(np.max(np.abs(seg))) * 2)
            times.append(tu[(i0 + i1) // 2])
    amps, times = np.array(amps), np.array(times)
    third = duration / 3
    c_t = tu[crossings] if crossings else np.array([])
    first_rate = np.sum(c_t < tu[0] + third) / third if third else 0
    last_rate = np.sum(c_t >= tu[0] + 2 * third) / third if third else 0
    first_amp = float(np.mean(amps[times < tu[0] + third])) if np.any(times < tu[0] + third) else 0.0
    last_amp = float(np.mean(amps[times >= tu[0] + 2 * third])) if np.any(times >= tu[0] + 2 * third) else 0.0
    return {
        "valid": flips >= 2,
        "flips": flips,
        "flips_per_s": round(flips / duration, 3),
        "amplitude_g": round(float(np.median(amps)) if amps.size else 0.0, 3),
        "rate_decrement_pct": round(_thirds_change(first_rate, last_rate), 1),
        "amp_decrement_pct": round(_thirds_change(first_amp, last_amp), 1),
        "rate_hz": round(rate, 1),
        "axis": "xyz"[axis],
    }


# --------------------------------------------------------------------------- tremor
def tremor(t, xyz, fs_max: float = 100.0) -> dict:
    """Postural/rest tremor while holding still. Strength = RMS of high-passed |a| in milli-g.
    Dominant frequency (3-12 Hz) only when the measured rate is >= 40 Hz."""
    t = np.asarray(t, dtype=float)
    xyz = np.asarray(xyz, dtype=float)
    if _too_short(t):
        return {"valid": False, "reason": "too few samples"}
    rate = measured_rate(t)
    fs = min(fs_max, rate)
    tu, a = resample(t, xyz, fs)
    mag = np.linalg.norm(a, axis=1)
    hp = _highpass(mag, fs, 2.0)
    # Also use the per-axis high-passed signal: |a| hides tremor orthogonal to gravity.
    hp_axes = _highpass(a, fs, 2.0)
    rms_mag = float(np.sqrt(np.mean(hp ** 2))) * 1000
    rms_vec = float(np.sqrt(np.mean(np.sum(hp_axes ** 2, axis=1)))) * 1000
    out = {
        "valid": True,
        "rms_mg": round(rms_mag, 2),
        "rms_vec_mg": round(rms_vec, 2),
        "rate_hz": round(rate, 1),
        "freq_enabled": rate >= TREMOR_FREQ_MIN_RATE_HZ,
        "dominant_hz": None,
        "band_power_frac": None,
    }
    if out["freq_enabled"] and len(hp) >= 64:
        # pick the axis with the most 3-12 Hz energy
        nper = min(len(hp), int(fs * 4))
        f, p = signal.welch(hp_axes, fs=fs, nperseg=nper, axis=0)
        band = (f >= 3) & (f <= 12)
        ax = int(np.argmax(p[band].sum(axis=0)))
        pb = p[:, ax]
        total = pb[(f >= 1)].sum()
        if band.any() and total > 0:
            out["dominant_hz"] = round(float(f[band][np.argmax(pb[band])]), 2)
            out["band_power_frac"] = round(float(pb[band].sum() / total), 3)
    return out


def is_still(xyz, max_sd_g: float = 0.15) -> bool:
    """Passive sampling gate: only score tremor when the wrist is roughly still."""
    xyz = np.asarray(xyz, dtype=float)
    if len(xyz) < 8:
        return False
    return bool(np.all(xyz.std(axis=0) < max_sd_g))


# --------------------------------------------------------------------------- taps
def alternating_taps(events, duration_s: float = 10.0) -> dict:
    """events: list of (t_seconds, button) presses, button in {'yellow','green'}.
    Only alternations count; a repeat of the same button is an error."""
    ev = sorted((float(t), b) for t, b in events if b in ("yellow", "green"))
    if not ev:
        return {"valid": False, "reason": "no taps", "taps": 0, "taps_per_s": 0.0}
    t0 = ev[0][0]
    valid_t, errors, prev = [], 0, None
    for t, b in ev:
        if b == prev:
            errors += 1
        else:
            valid_t.append(t)
        prev = b
    valid_t = np.array(valid_t)
    duration = max(duration_s, 1e-6)
    iti = np.diff(valid_t)
    cv = float(np.std(iti) / np.mean(iti)) if iti.size >= 2 and np.mean(iti) > 0 else None
    third = duration / 3
    first = np.sum(valid_t < t0 + third) / third
    last = np.sum(valid_t >= t0 + 2 * third) / third
    return {
        "valid": len(valid_t) >= 3,
        "taps": int(len(valid_t)),
        "errors": int(errors),
        "taps_per_s": round(len(valid_t) / duration, 3),
        "iti_cv": round(cv, 3) if cv is not None else None,
        "rate_decrement_pct": round(_thirds_change(first, last), 1),
    }


# --------------------------------------------------------------------------- voice
def voice(samples, fs: float = 8000.0, win_s: float = 0.1) -> dict:
    """Sustained 'ahhh'. Loudness = RMS of voiced windows in dBFS; stability = CV of
    window RMS across voiced windows (lower = steadier)."""
    x = np.asarray(samples, dtype=float)
    if x.size < fs * 0.5:
        return {"valid": False, "reason": "too few samples"}
    x = x - np.mean(x)  # mic has a large DC offset
    x = _highpass(x, fs, 80.0)
    n = int(fs * win_s)
    k = x.size // n
    w = x[: k * n].reshape(k, n)
    rms = np.sqrt(np.mean(w ** 2, axis=1))
    # Voiced = within ~9 dB of the loud part, and above an absolute mic-noise floor.
    thresh = max(0.35 * np.percentile(rms, 90), VOICE_ABS_FLOOR)
    voiced = rms[rms > thresh]
    clip = float(np.mean(np.abs(np.asarray(samples)) >= 32000))
    if voiced.size < 3:
        return {"valid": False, "reason": "no sustained voice", "voiced_s": round(voiced.size * win_s, 2)}
    level = float(np.sqrt(np.mean(voiced ** 2)))
    return {
        "valid": True,
        "loudness_dbfs": round(20 * np.log10(level / 32768.0), 2),
        "stability_cv": round(float(np.std(voiced) / np.mean(voiced)), 3),
        "voiced_s": round(voiced.size * win_s, 2),
        "clip_frac": round(clip, 4),
    }
