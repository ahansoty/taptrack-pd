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
    assert types[0] == "check_started" and types[-2:] == ["check_result", "device"]
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


def test_disconnect_switches_to_demo_replay(store, monkeypatch):
    """A FREE-WILi that drops (unplugged during judging) -> simulated replay keeps the dashboard live."""
    from taptrack import bridge as bridge_mod, config
    from taptrack.device import FreeWiliDevice

    class FlakyWili(FreeWiliDevice):
        def open(self):
            self.connected = True
            return True

        def _call(self, label, fn, *args):
            return True

        def pump(self, seconds=0.02):
            self.connected = False  # cable pulled

    monkeypatch.setattr(config, "DEMO_MODE", True)
    monkeypatch.setattr(config, "USE_DEVICE", False)
    events = []
    b = bridge_mod.Bridge(store, events.append)
    dev = FlakyWili()
    class AnyLib:  # stands in for the freewili object; every method is a no-op
        def __getattr__(self, name):
            return lambda *a, **k: None

    dev.dev = AnyLib()
    dev.open()
    b._attach(dev)
    b._tick()   # pump -> disconnected
    b._tick()   # detects it -> demo
    assert b.demo and b.device.name == "simulated" and b.device.connected
    assert any(e["type"] == "alert" and "demo replay" in e["text"] for e in events)
    assert b.status()["state"] == "demo"


def test_dashboard_simulated_check_on_real_device_measures_all_tests(store):
    """Regression: a simulated check started while a real device is attached must stream sim accel."""
    from taptrack.device import FreeWiliDevice

    class IdleWili(FreeWiliDevice):
        def _call(self, label, fn, *args):
            return True

        def pump(self, seconds=0.02):
            import time as _t
            _t.sleep(seconds)

    events = []
    b = Bridge(store, events.append, duration_scale=0.15, auto_advance=True)
    dev = IdleWili()
    dev.connected = True

    class AnyLib:
        def __getattr__(self, name):
            return lambda *a, **k: None

    dev.dev = AnyLib()
    b._attach(dev)
    row = b.run_check(simulate=True, state=0.9)
    assert set(row["tests"]) == {"flip", "tremor", "taps", "voice"}, row["results"]
    assert b.device is dev
    assert events[-1]["type"] == "device" and events[-1]["state"] != "check"


def test_watch_flow_main_result_hold_and_dismiss(store, monkeypatch):
    """Idle = main screen; after a check: calc -> result for 60 s; any button returns to main
    without starting anything."""
    import time as _t
    events = []
    dev = SimDevice(state=0.9, seed=3)
    b = Bridge(store, events.append, device=dev, duration_scale=0.15, auto_advance=True)
    dev.open()
    b._attach(dev)
    assert b._desired_home() == "home_n"
    row = b.run_check()
    shown = [l for l in dev.log if l.startswith("image:") or l.startswith("screen:")]
    # the wrist's result screen matches the level the dashboard receives
    assert b._home_override[0] == {"good": "res_g", "fair": "res_y", "low": "res_r"}[row["level"]]
    assert "calc" in " ".join(shown)
    assert b._home_override and b._home_override[0].startswith("res_")
    assert b._home_override[1] - _t.time() > 50          # held ~60 s
    dev._press("blue")                                    # any button: dismiss only
    b._tick()
    assert b._home_override is None and b._desired_home() == "home_n"
    assert len(store.checks(_t.time() - 300, source="demo")) == 1   # no second check started
    b._home_override = ("res_g", _t.time() - 1)          # expiry -> main
    assert b._desired_home() == "home_n"


def test_idle_is_always_main_screen(store):
    import time as _t
    b = Bridge(store, lambda e: None)
    b.device = SimDevice()
    now = _t.time()
    for src, lvl in (("synthetic", "low"), ("demo", "low"), ("device", "good")):
        store.add_check(now - 60, 50, lvl, {}, {}, {}, source=src)
        assert b._desired_home() == "home_n"


def test_result_shows_fast_even_if_database_fails(store):
    """The wrist shows the result right after the last test, even when saving fails."""
    import time as _t
    dev = SimDevice(state=0.9, seed=5)
    events = []
    b = Bridge(store, events.append, device=dev, duration_scale=0.15, auto_advance=True)
    dev.open()
    b._attach(dev)

    def boom(*a, **k):
        raise RuntimeError("database unreachable")

    store.add_check = boom
    t0 = _t.time()
    row = b.run_check()
    assert row and row.get("save_error") and row["score"] is not None
    assert b._home_override and b._home_override[0].startswith("res_")
    assert b.state != "check"
    assert any(e["type"] == "check_result" for e in events)
