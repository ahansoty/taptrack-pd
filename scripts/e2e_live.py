"""End-to-end: open the clinician dashboard and wait for a live check result to arrive over the websocket.

    python scripts/e2e_live.py [base_url] [--start] [--good]
    (--start triggers a simulated check first: a "much lower" one by default, which alerts the caregiver when
     Photon is on; add --good for a Good check that never sends a message)
"""
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

base = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    steps = []
    pg.on("websocket", lambda ws: ws.on("framereceived", lambda f: steps.append(f) if '"step"' in str(f) else None))
    pg.request.post(base + "/api/login", data={"email": "clinician@example.com", "role": "clinician"})
    pg.goto(base + "/")
    pg.wait_for_timeout(1500)
    if "--start" in sys.argv:
        httpx.post(base + "/api/check/start", json={"simulate": True, "state": 0.88 if "--good" in sys.argv else 0.05})
    t0 = time.time()
    pg.wait_for_function("document.querySelector('#live-result .num') !== null", timeout=150000)
    score = pg.inner_text("#live-result .num")
    print(f"live result arrived over websocket after {time.time() - t0:.0f} s: score {score}; {len(steps)} step events")
    pg.wait_for_timeout(2500)
    pg.screenshot(path="data/shots/e2e-live.png", full_page=False)
    feed = pg.inner_text("#feed")
    print("activity feed:", " | ".join(feed.splitlines()[:8]))
    b.close()
