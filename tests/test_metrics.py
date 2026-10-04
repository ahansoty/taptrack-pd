import numpy as np
import pytest

from taptrack import metrics, scoring

RNG = np.random.default_rng(0)


def bursty_times(duration, rate, jitter=0.3):
    """Uneven sample times like the USB event stream."""
    n = int(duration * rate)
    dt = (1 / rate) * (1 + jitter * RNG.uniform(-1, 1, n))
    return np.cumsum(dt)


def flip_signal(t, flip_hz, amp=1.0, fade=0.0, noise=0.03):
    """Gravity swinging on z between +amp and -amp; flip_hz flips/s = flip_hz/2 cycles/s."""
    env = amp * (1 - fade * (t - t[0]) / (t[-1] - t[0]))
    z = env * np.sin(np.pi * flip_hz * t)
    x = 0.1 * np.ones_like(t)
    y = np.sqrt(np.clip(1 - z ** 2, 0, 1))
    return np.column_stack([x, y, z]) + noise * RNG.standard_normal((len(t), 3))


def test_resample_uniform():
    t = bursty_times(2, 50)
    tu, x = metrics.resample(t, np.sin(t), 50)
    assert np.allclose(np.diff(tu), 1 / 50)
    assert np.allclose(x, np.sin(tu), atol=0.01)


@pytest.mark.parametrize("flip_hz", [2.0, 4.0, 6.0])
def test_hand_flip_rate(flip_hz):
    t = bursty_times(10, 79)
    r = metrics.hand_flip(t, flip_signal(t, flip_hz))
    assert r["valid"]
    assert r["flips_per_s"] == pytest.approx(flip_hz, rel=0.12)
    assert r["axis"] == "z"
    assert r["amplitude_g"] == pytest.approx(2.0, rel=0.15)


def test_hand_flip_decrement():
    t = bursty_times(10, 79)
    steady = metrics.hand_flip(t, flip_signal(t, 4.0))
    fading = metrics.hand_flip(t, flip_signal(t, 4.0, fade=0.6))
    assert abs(steady["amp_decrement_pct"]) < 10
    assert fading["amp_decrement_pct"] > 25


def test_hand_flip_still_wrist_has_no_flips():
    t = bursty_times(10, 79)
    xyz = np.column_stack([np.zeros_like(t), np.zeros_like(t), np.ones_like(t)])
    r = metrics.hand_flip(t, xyz + 0.01 * RNG.standard_normal(xyz.shape))
    assert r["flips"] <= 1 and not r["valid"]


def tremor_xyz(t, freq, amp_g, noise=0.003):
    xyz = np.column_stack([np.zeros_like(t), np.zeros_like(t), np.ones_like(t)])
    xyz[:, 0] += amp_g * np.sin(2 * np.pi * freq * t)
    xyz[:, 2] += 0.5 * amp_g * np.sin(2 * np.pi * freq * t + 0.3)
    return xyz + noise * RNG.standard_normal(xyz.shape)


@pytest.mark.parametrize("freq", [4.5, 6.0, 9.0])
def test_tremor_frequency_at_high_rate(freq):
    t = bursty_times(20, 79, jitter=0.1)
    r = metrics.tremor(t, tremor_xyz(t, freq, 0.05))
    assert r["freq_enabled"]
    assert r["dominant_hz"] == pytest.approx(freq, abs=0.5)
    assert r["band_power_frac"] > 0.5


def test_tremor_strength_scales_and_freq_disabled_at_low_rate():
    t = bursty_times(20, 18)
    weak = metrics.tremor(t, tremor_xyz(t, 3.0, 0.01))
    strong = metrics.tremor(t, tremor_xyz(t, 3.0, 0.08))
    assert not strong["freq_enabled"] and strong["dominant_hz"] is None
    assert strong["rms_vec_mg"] > 4 * weak["rms_vec_mg"]


def test_tremor_rms_known_amplitude():
    t = bursty_times(20, 100, jitter=0.05)
    xyz = np.column_stack([0.05 * np.sin(2 * np.pi * 6 * t), np.zeros_like(t), np.ones_like(t)])
    r = metrics.tremor(t, xyz)
    assert r["rms_vec_mg"] == pytest.approx(50 / np.sqrt(2), rel=0.1)


def test_is_still():
    t = bursty_times(5, 79)
    assert metrics.is_still(tremor_xyz(t, 5, 0.01))
    assert not metrics.is_still(flip_signal(t, 3))


def make_taps(rate, duration=10, jitter=0.0, slow_down=0.0, errors=0):
    ev, t, b = [], 0.0, "yellow"
    base = 1 / rate
    while t < duration:
        ev.append((t, b))
        b = "green" if b == "yellow" else "yellow"
        frac = t / duration
        t += base * (1 + slow_down * frac) * (1 + jitter * RNG.uniform(-1, 1))
    for i in range(errors):
        ev.append((ev[5 + i * 3][0] + 0.01, ev[5 + i * 3][1]))
    return ev


def test_taps_rate_and_regular():
    r = metrics.alternating_taps(make_taps(5.0))
    assert r["taps_per_s"] == pytest.approx(5.0, rel=0.05)
    assert r["iti_cv"] < 0.02
    assert r["errors"] == 0


def test_taps_irregular_and_errors():
    r = metrics.alternating_taps(make_taps(4.0, jitter=0.5, errors=3))
    assert r["iti_cv"] > 0.15
    assert r["errors"] == 3


def test_taps_decrement():
    r = metrics.alternating_taps(make_taps(5.0, slow_down=1.5))
    assert r["rate_decrement_pct"] > 20


def test_taps_empty():
    assert not metrics.alternating_taps([])["valid"]


def voice_samples(seconds=5, fs=8000, level=6000, wobble=0.0, dc=-1200):
    t = np.arange(int(seconds * fs)) / fs
    env = level * (1 + wobble * np.sin(2 * np.pi * 1.5 * t))
    x = env * np.sin(2 * np.pi * 180 * t) + dc + 100 * RNG.standard_normal(t.size)
    x[: int(0.5 * fs)] = dc + 100 * RNG.standard_normal(int(0.5 * fs))  # silence at start
    return x.astype(int)


def test_voice_loudness_ignores_dc_and_silence():
    loud = metrics.voice(voice_samples(level=8000))
    quiet = metrics.voice(voice_samples(level=2000))
    assert loud["valid"] and quiet["valid"]
    assert loud["loudness_dbfs"] - quiet["loudness_dbfs"] == pytest.approx(12.0, abs=1.0)
    assert loud["voiced_s"] == pytest.approx(4.5, abs=0.3)


def test_voice_stability():
    steady = metrics.voice(voice_samples(wobble=0.0))
    shaky = metrics.voice(voice_samples(wobble=0.5))
    assert steady["stability_cv"] < 0.05 < shaky["stability_cv"]


def test_voice_silence_invalid():
    assert not metrics.voice(np.full(40000, -1200) + RNG.integers(-50, 50, 40000))["valid"]


# ------------------------------------------------------------------ scoring
def results_at(factor):
    """factor 1.0 = at default baseline, <1 = worse."""
    b = {k: v[0] for k, v in scoring.DEFAULT_BASELINE.items()}
    return {
        "flip": {"valid": True, "flips_per_s": b["flip_rate"] * factor, "amplitude_g": b["flip_amp"] * factor,
                 "amp_decrement_pct": b["flip_dec"] / factor},
        "tremor": {"valid": True, "rms_vec_mg": b["tremor_rms"] / factor},
        "taps": {"valid": True, "taps_per_s": b["tap_rate"] * factor, "iti_cv": b["tap_cv"] / factor,
                 "rate_decrement_pct": b["tap_dec"] / factor},
        "voice": {"valid": True, "loudness_dbfs": b["voice_db"] - 10 * (1 - factor), "stability_cv": b["voice_cv"] / factor},
    }


def test_score_at_baseline_is_85_and_monotonic():
    s1 = scoring.score(results_at(1.0))
    s2 = scoring.score(results_at(0.8))
    s3 = scoring.score(results_at(0.6))
    assert s1["score"] == 85 and s1["level"] == "good"
    assert s1["score"] > s2["score"] > s3["score"]
    assert s3["level"] in ("fair", "low")
    assert 0 <= s3["score"] <= 100


def test_score_handles_missing_tests():
    r = results_at(1.0)
    del r["voice"]
    r["taps"] = {"valid": False}
    s = scoring.score(r)
    assert s["score"] == 85 and set(s["tests"]) == {"flip", "tremor"}
    assert scoring.score({})["score"] is None


def test_personal_baseline():
    hist = [scoring.extract(results_at(f)) for f in (0.5, 0.52, 0.48, 0.5)]
    base = scoring.baseline_from(hist)
    # a reading equal to this person's own (low) baseline scores 85, not low
    assert scoring.score(results_at(0.5), base)["score"] == pytest.approx(85, abs=2)
