import time

from taptrack import finchnode, report, synth
from taptrack.storage import Storage


def test_guard_removes_dose_advice_only():
    text = ("Scores drop about 3 h after each dose. Consider increasing the levodopa dose to 150 mg.\n"
            "- The interval between doses should be shortened.\n"
            "- Tremor is strongest in the late afternoon.\n"
            "The patient might add an extra pill at 2 PM. Voice loudness is stable.")
    out, removed = report.guard(text)
    assert removed == 3
    assert "Scores drop" in out and "Tremor is strongest" in out and "Voice loudness" in out
    assert "increasing" not in out and "shortened" not in out and "extra pill" not in out


def test_template_report_patterns_only(tmp_path):
    store = Storage(url="", sqlite_path=tmp_path / "r.db")
    synth.load_into(store, end_ts=time.mktime(time.strptime("2026-10-04 12:30", "%Y-%m-%d %H:%M")))
    r = report.generate(store)
    assert r["engine"] == "template"
    assert "Wearing-off pattern" in r["neurologist_report"] and "Not a diagnostic device" in r["patient_summary"]
    assert r["advice_sentences_removed"] == 0
    assert report.guard(r["neurologist_report"])[1] == 0
    assert store.get_setting("latest_report")["generated_at"] == r["generated_at"]


def test_doses_per_day_parsing():
    assert finchnode.doses_per_day("Take 1 tablet four times daily") == 4
    assert finchnode.doses_per_day("1 tab PO TID") == 3
    assert finchnode.doses_per_day("q4h while awake") == 6
    assert finchnode.doses_per_day("5 times a day") == 5
    assert finchnode.doses_per_day("as needed") is None


def test_summarize_uses_levodopa_order():
    rec = {"id": "r1", "data": {
        "demographics": {"name": "Alex Doe (synthetic)", "birthDate": "1950-01-01", "gender": "male"},
        "conditions": [{"name": "Parkinson's disease"}],
        "medications": [{"name": "carbidopa 25 MG / levodopa 100 MG Oral Tablet", "frequency": "three times daily",
                         "status": "active"}, {"name": "metformin", "status": "stopped"}]}}
    s = finchnode.summarize(rec)
    assert s["name"] == "Alex Doe" and s["age"] >= 75
    assert s["levodopa_order"].startswith("carbidopa") and s["dose_times"] == ["08:00", "13:00", "18:00"]
    assert len(s["medications"]) == 1


def test_summarize_without_levodopa_falls_back():
    s = finchnode.summarize({"data": {"demographics": {}, "medications": [{"name": "apixaban", "status": "active"}]}})
    assert s["levodopa_order"] is None and s["schedule_source"] == "TapTrack configuration"


def test_observation_is_fhir_shaped():
    o = finchnode.observation({"ts": time.time(), "score": 72, "tests": {"flip": 80.0}, "minutes_since_dose": 95})
    assert o["resourceType"] == "Observation" and o["valueQuantity"]["value"] == 72
    assert any("minutes since" in c["code"]["text"] for c in o["component"])
