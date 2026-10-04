import time

import pytest

from taptrack import synth
from taptrack.bridge import Bridge
from taptrack.device import SimDevice
from taptrack.storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(url="", sqlite_path=tmp_path / "t.db")


def test_storage_roundtrip(store):
    now = time.time()
    store.add_dose(now - 3600)
    row = store.add_check(now, 80, "good", {"flip": 80}, {"flip_rate": 3.5}, {"flip": {"valid": True}})
    assert row["minutes_since_dose"] == pytest.approx(60, abs=0.2)
    got = store.checks(now - 10)
    assert got[0]["tests"] == {"flip": 80} and got[0]["score"] == 80
    store.add_passive(now, 30.0, 5.1)
    assert store.passive(now - 1)[0]["rms_mg"] == 30.0
    store.set_setting("k", {"a": 1})
    assert store.get_setting("k") == {"a": 1}


def test_wearing_off_model_shape():
    on = synth.benefit(1.5)
    early = synth.benefit(0.2)
    late = synth.benefit(3.9)
    assert on > 0.9 and early < 0.3 and late < 0.3
    # trend: wearing-off starts earlier on the last day
    assert synth.benefit(3.1, 1.0) < synth.benefit(3.1, 0.0)


def test_synthetic_dataset(store):
    end = time.mktime(time.strptime("2026-10-04 12:30", "%Y-%m-%d %H:%M"))
    stats = synth.load_into(store, days=14, end_ts=end)
    assert stats["doses"] == 13 * 4 + 2  # today: 8 AM and noon
    assert stats["checks"] > 100 and stats["approx_missed"] >= 5
    b = stats["score_by_time_since_dose"]
    # peak around 1-2 h after a dose, dip before the next dose
    assert b["60-120 min"] > b["180-240 min"] + 15
    assert b["60-120 min"] > b["0-30 min"]
    assert stats["last_quarter_mean"] < stats["first_quarter_mean"]
    # reloading replaces, doesn't duplicate
    synth.load_into(store, days=14, end_ts=end)
    assert store.count("checks") == stats["checks"]


@pytest.mark.parametrize("state,lo,hi", [(1.0, 70, 100), (0.0, 0, 55)])
def test_simulated_check_end_to_end(store, state, lo, hi):
    events = []
    dev = SimDevice(state=state, seed=1)
    b = Bridge(store, events.append, device=dev, duration_scale=0.15, auto_advance=True)
    dev.open()
    b._attach(dev)
    b._synthetic_state_now = lambda: state
    row = b.run_check()
    assert row is not None and row["complete"]
    assert set(row["tests"]) == {"flip", "tremor", "taps", "voice"}, row["results"]
    assert lo <= row["score"] <= hi, (row["score"], row["metrics"])
    types = [e["type"] for e in events]
    assert types[0] == "check_started" and types[-1] == "check_result"
    assert types.count("step") == 12
    assert any("speak" in line for line in dev.log)
    assert store.latest_check()["id"] == row["id"]


def test_red_button_logs_dose(store):
    events = []
    dev = SimDevice()
    b = Bridge(store, events.append, device=dev)
    dev.open()
    b._attach(dev)
    dev._press("red")
    b._tick()
    assert len(store.doses()) == 1 and events[-1]["type"] == "dose"
