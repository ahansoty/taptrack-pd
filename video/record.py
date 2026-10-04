"""Record real dashboard footage for the video (Playwright, 1920x1080) against the running TapTrack server.

    python video/record.py live      # a simulated Good check landing live + websocket timeline (no messages sent)
    python video/record.py pattern   # 14-day simulated history, visit report, FinchNode record
    python video/record.py caregiver # caregiver view
    python video/record.py agent     # Simulate wearing-off check -> agent feed (sends a real caregiver iMessage if Photon runs)
"""
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "rec"
W, H = 1920, 1080          # output frame
ZOOM = 4 / 3   # lay the page out like a 1440-wide window, rendered crisp at 1920x1080


def smooth_scroll(pg, to_y, steps=45, pause=22):
    cur = pg.evaluate("window.scrollY")
    for i in range(1, steps + 1):
        e = i / steps
        e = e * e * (3 - 2 * e)  # ease in-out
        pg.evaluate(f"window.scrollTo(0, {cur + (to_y - cur) * e})")
        pg.wait_for_timeout(pause)


def y_of(pg, sel, pad=20):
    return pg.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top + window.scrollY - {pad}")


def session(p, role="clinician"):
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                        record_video_dir=str(OUT / "_tmp"), record_video_size={"width": W, "height": H})
    ctx.add_init_script(f"document.addEventListener('DOMContentLoaded', () => document.documentElement.style.zoom = '{ZOOM}')")
    ctx.request.post(BASE + "/api/login", data={"email": "dr.patel@example.com" if role == "clinician" else "family@example.com", "role": role})
    return b, ctx


def finish(b, ctx, pg, name, meta=None):
    video = pg.video.path()
    ctx.close()
    b.close()
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{name}.webm"
    shutil.move(video, dst)
    if meta is not None:
        (OUT / f"{name}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print("saved", dst)


def rec_live():
    with sync_playwright() as p:
        b, ctx = session(p)
        t0 = time.time()
        pg = ctx.new_page()
        events = []
        pg.on("websocket", lambda ws: ws.on("framereceived", lambda f: events.append({"t": round(time.time() - t0, 2), "data": f if isinstance(f, str) else str(f)})))
        pg.goto(BASE + "/")
        pg.wait_for_timeout(2500)
        httpx.post(BASE + "/api/check/start", json={"simulate": True, "state": 0.88})
        start = time.time() - t0
        pg.wait_for_function("document.querySelector('#live-result .num') !== null", timeout=150000)
        pg.wait_for_timeout(3500)
        evs = []
        for e in events:
            try:
                d = json.loads(e["data"])
                evs.append({"t": e["t"], "type": d.get("type"), "step": d.get("step"), "phase": d.get("phase"),
                            "score": d.get("score"), "level": d.get("level")})
            except Exception:
                pass
        finish(b, ctx, pg, "live", {"check_requested_at": round(start, 2), "events": evs})


def rec_pattern(day: str):
    with sync_playwright() as p:
        b, ctx = session(p)
        pg = ctx.new_page()
        pg.goto(BASE + f"/?date={day}")
        pg.wait_for_timeout(3500)
        for x in range(260, 1200, 18):                       # sweep the day curve tooltip
            pg.mouse.move(x, 600)
            pg.wait_for_timeout(28)
        smooth_scroll(pg, y_of(pg, "#h-curve"))
        pg.wait_for_timeout(600)
        for x in range(160, 860, 16):                        # sweep the dose-response curve
            pg.mouse.move(x, 330)
            pg.wait_for_timeout(32)
        pg.mouse.move(1400, 360)
        pg.wait_for_timeout(2500)                            # heatmap visible on the right
        smooth_scroll(pg, y_of(pg, "#h-report", 90))
        pg.click("#btn-report")
        pg.wait_for_function("!document.querySelector('#btn-report').disabled", timeout=90000)
        pg.wait_for_timeout(1500)
        for _ in range(16):                                  # scroll inside the report box
            pg.evaluate("document.querySelector('#rep-neuro').scrollBy(0, 28)")
            pg.wait_for_timeout(110)
        pg.click("#tab-patient")
        pg.wait_for_timeout(3000)
        finish(b, ctx, pg, "pattern")


def rec_caregiver():
    with sync_playwright() as p:
        b, ctx = session(p, "clinician")
        pg = ctx.new_page()
        pg.goto(BASE + "/caregiver")
        pg.wait_for_timeout(9000)
        finish(b, ctx, pg, "caregiver")


def rec_feed():
    """Agent activity after the report request (no messages sent)."""
    with sync_playwright() as p:
        b, ctx = session(p)
        pg = ctx.new_page()
        pg.goto(BASE + "/")
        pg.wait_for_timeout(2000)
        smooth_scroll(pg, y_of(pg, "#h-agent", 120))
        pg.wait_for_timeout(9000)
        finish(b, ctx, pg, "feed")


def rec_agent():
    with sync_playwright() as p:
        b, ctx = session(p)
        pg = ctx.new_page()
        pg.goto(BASE + "/")
        pg.wait_for_timeout(2000)
        smooth_scroll(pg, y_of(pg, "#h-agent", 260))
        pg.wait_for_timeout(1000)
        pg.click("#btn-sim-low")
        pg.wait_for_timeout(1500)
        smooth_scroll(pg, 0)
        pg.wait_for_function("document.querySelector('#live-result .num') !== null", timeout=150000)
        pg.wait_for_timeout(2500)
        smooth_scroll(pg, y_of(pg, "#h-agent", 260))
        pg.wait_for_function("document.querySelector('#agent-feed').innerText.includes('caregiver alert')", timeout=60000)
        pg.wait_for_timeout(4000)                            # agent's caregiver alert in the feed
        # ask the agent (through Agentverse, like ASI:One) to send the visit report
        import subprocess
        chat = subprocess.Popen([str(HERE.parent / "agent" / ".venv" / "Scripts" / "python"), "-u",
                                 str(HERE.parent / "agent" / "test_chat.py"), "Send the visit report to her neurologist"],
                                stdout=open(OUT / "agent_chat.log", "w"), stderr=subprocess.STDOUT)
        pg.wait_for_function("document.querySelector('#agent-feed').innerText.includes('offered')", timeout=120000)
        pg.wait_for_timeout(6000)
        chat.wait(timeout=60)
        finish(b, ctx, pg, "agent")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "live"
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    {"live": rec_live, "pattern": lambda: rec_pattern(yesterday), "caregiver": rec_caregiver, "agent": rec_agent, "feed": rec_feed}[what]()
