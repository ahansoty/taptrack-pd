import time

from taptrack import notify, report
from taptrack.storage import Storage


def make_store(tmp_path):
    s = Storage(url="", sqlite_path=tmp_path / "n.db")
    now = time.time()
    s.add_dose(now - 3 * 3600)
    s.add_check(now - 60, 38, "low", {"flip": 40}, {}, {}, source="device")
    return s


def test_red_alert_text_has_score_usual_and_hours():
    c = {"ts": time.time(), "score": 38.2, "level": "low", "minutes_since_dose": 190}
    t = notify.red_alert(c)
    assert "much lower than usual" in t and "score 38" in t and "usual is about 85" in t and "3 h 10 min" in t
    assert report.guard(t)[1] == 0


def test_messages_have_no_dose_advice():
    for t in (notify.missed_reminder({"ts": time.time()}),
              notify.report_sent("Dr. X", "Mon 10:30 AM", 150)):
        assert report.guard(t)[1] == 0


def test_send_without_sidecar_fails_gracefully(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTON_PORT", "1")  # nothing listens there
    s = make_store(tmp_path)
    r = notify.send("caregiver", "hi", s, kind="test_message")
    assert r["ok"] is False and "offline" in r["error"]
    assert s.actions(1)[0]["detail"]["sent"] is False


def test_chat_context_and_refusal(tmp_path):
    s = make_store(tmp_path)
    a1 = notify.chat_reply(s, "+1555", "how is she doing today?")
    assert a1.startswith("Today:") and "1 check," in a1 and "(s)" not in a1 and " logged" in a1
    a2 = notify.chat_reply(s, "+1555", "and the afternoon?")  # follow-up keeps the day
    assert a2.startswith("Today:")
    assert "can't give medication advice" in notify.chat_reply(s, "+1555", "should she take an extra pill?")
    assert "Last dose logged" in notify.chat_reply(s, "+1555", "when was the last dose")
    assert len(s.get_setting("chat:+1555")["turns"]) == 4


def test_good_check_never_triggers_alert(monkeypatch):
    from taptrack import config, server
    sent = []
    monkeypatch.setattr(config, "DEMO_MODE", False)
    monkeypatch.setattr(server.notify, "send", lambda *a, **k: sent.append(a) or {"ok": True})
    monkeypatch.setattr(server, "agent_alive", lambda: False)
    monkeypatch.setitem(server.state, "store", None)
    for level, score in (("good", 88), ("fair", 60)):
        server._fallback_alert({"ts": time.time(), "score": score, "level": level, "source": "device"})
    assert sent == []
    server._fallback_alert({"ts": time.time(), "score": 30, "level": "low", "source": "device", "minutes_since_dose": 200})
    assert len(sent) == 1 and "much lower than usual" in sent[0][1]
