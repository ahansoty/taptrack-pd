import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["SQLITE_PATH"] = str(tmp_path_factory.mktemp("db") / "api.db")
    os.environ["BRIDGE"] = "false"
    import importlib

    from taptrack import config, storage
    importlib.reload(config)
    storage._store = None
    from taptrack import server
    importlib.reload(server)
    with TestClient(server.app) as c:
        yield c, server


def test_pages_and_status(client):
    c, _ = client
    assert c.get("/").status_code == 200
    assert c.get("/caregiver").status_code == 200
    s = c.get("/api/status").json()
    assert s["storage"] == "sqlite" and s["baseline_set"]


def test_data_endpoints(client):
    c, _ = client
    assert len(c.get("/api/checks").json()) > 100
    hm = c.get("/api/heatmap").json()
    assert len(hm["rows"]) == 14 and len(hm["bins"]) == 9
    summ = c.get("/api/summary").json()
    assert summ["wearing_off"]["detected"] is True
    assert summ["n_missed_checks"] > 0
    t = c.get("/api/today").json()
    assert "checks" in t and "doses" in t
    cg = c.get("/api/caregiver").json()
    assert "missed_today" in cg


def test_dose_without_bridge(client):
    c, _ = client
    before = len(c.get("/api/today").json()["doses"])
    assert "ts" in c.post("/api/dose", json={"source": "test"}).json()
    assert len(c.get("/api/today").json()["doses"]) == before + 1


def test_websocket_receives_published_events(client):
    c, server = client
    with c.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        server.hub.publish({"type": "check_result", "score": 77})
        msg = ws.receive_json()
        assert msg["type"] == "check_result" and msg["score"] == 77


def test_agent_action_roundtrip(client):
    c, _ = client
    c.post("/api/actions", json={"kind": "reminder", "detail": {"text": "hi"}})
    assert c.get("/api/actions").json()[0]["kind"] == "reminder"
