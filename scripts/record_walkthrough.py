"""Record a silent screen-capture walkthrough of the dashboard (B-roll for the demo video).

    python scripts/record_walkthrough.py [base_url]  -> data/video/walkthrough.mp4

Does not start a check or send messages (pass --live to include a simulated wearing-off check,
which makes the agent text the caregiver).
"""
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

base = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
out = Path("data/video")
out.mkdir(parents=True, exist_ok=True)
W, H = 1600, 900


def smooth_scroll(pg, to_y, steps=40, pause=25):
    cur = pg.evaluate("window.scrollY")
    for i in range(1, steps + 1):
        pg.evaluate(f"window.scrollTo(0, {cur + (to_y - cur) * i / steps})")
        pg.wait_for_timeout(pause)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(out), record_video_size={"width": W, "height": H})
    pg = ctx.new_page()
    pg.request.post(base + "/api/login", data={"email": "clinician@example.com", "role": "clinician"})
    pg.goto(base + "/")
    pg.wait_for_timeout(3500)                       # latest check + 14-day tiles
    y = lambda sel: pg.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top + window.scrollY - 24")
    smooth_scroll(pg, y("#h-today"))
    pg.mouse.move(700, 520)                         # hover the today curve for a tooltip
    for x in range(300, 1050, 25):
        pg.mouse.move(x, 560)
        pg.wait_for_timeout(40)
    pg.wait_for_timeout(1500)
    smooth_scroll(pg, y("#h-curve"))
    for x in range(150, 700, 20):
        pg.mouse.move(x, 380)
        pg.wait_for_timeout(40)
    pg.wait_for_timeout(2500)                       # dose response + heatmap
    smooth_scroll(pg, y("#h-tests"))
    pg.wait_for_timeout(2000)
    pg.click("#btn-report")
    pg.wait_for_function("!document.querySelector('#btn-report').disabled", timeout=60000)
    pg.wait_for_timeout(4000)                       # neurologist report
    pg.click("#tab-patient")
    pg.wait_for_timeout(3500)                       # patient summary
    smooth_scroll(pg, y("#h-record"))
    pg.wait_for_timeout(3500)                       # FinchNode record + agent activity
    if "--live" in sys.argv:
        pg.click("#btn-sim-low")
        smooth_scroll(pg, 0)
        pg.wait_for_function("document.querySelector('#live-result .num') !== null", timeout=150000)
        pg.wait_for_timeout(4000)
    pg.goto(base + "/caregiver")
    pg.wait_for_timeout(5000)                       # caregiver view
    smooth_scroll(pg, 600)
    pg.wait_for_timeout(2500)
    video = pg.video.path()
    ctx.close()
    b.close()

mp4 = out / "walkthrough.mp4"
ff = shutil.which("ffmpeg")
if ff:
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "20", "-movflags", "+faststart", str(mp4)], check=True)
    Path(video).unlink(missing_ok=True)
    print("saved", mp4)
else:
    print("saved", video)
