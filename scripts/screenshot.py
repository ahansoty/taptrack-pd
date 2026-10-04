"""Screenshot the dashboards (light + dark) for review: python scripts/screenshot.py [base_url] [outdir]"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "data/shots"); out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    import httpx
    shots = [("login", "/login", 1400)]
    for scheme in ("light",):
        for name, path, w in (("login", "/login", 1400), ("clinician", "/", 1400), ("caregiver", "/caregiver", 1400), ("clinician-phone", "/", 390)):
            ctx = b.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme)
            role = "caregiver" if name.startswith("caregiver") else "clinician"
            ctx.request.post(base + "/api/login", data={"email": f"{role}@example.com", "role": role})
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + path); pg.wait_for_timeout(1800)
            f = out / f"{name}-{scheme}.png"; pg.screenshot(path=str(f), full_page=True)
            sw = pg.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            print(f, "errors:", errs, "hscroll:", sw)
    b.close()
