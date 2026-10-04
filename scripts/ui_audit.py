"""Click through every dashboard view and button; flag broken text, console errors and layout overflow.

    python scripts/ui_audit.py [base_url]     -> data/shots/audit-*.png and a printed report

Does not trigger simulated checks or real messages unless --live is passed.
"""
import re
import sys

from playwright.sync_api import sync_playwright

base = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
BAD = re.compile(r"\bundefined\b|\bNaN\b|\bnull\b|\(s\)|\[object|Infinity|…\s*$")
problems = []


def check_text(pg, where):
    txt = pg.inner_text("body")
    for m in BAD.finditer(txt):
        ctx = txt[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")
        problems.append(f"{where}: suspicious text '{m.group(0)}' in '...{ctx}...'")
    if pg.evaluate("document.documentElement.scrollWidth > innerWidth"):
        problems.append(f"{where}: horizontal scroll")


with sync_playwright() as p:
    b = p.chromium.launch()
    for width, tag in ((1400, "desk"), (390, "phone")):
        ctx = b.new_context(viewport={"width": width, "height": 900})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))

        # signed out -> login
        pg.goto(base + "/")
        assert pg.url.endswith("/login"), pg.url
        pg.click("button[type=submit]")
        if "valid email" not in pg.inner_text("#err"):
            problems.append(f"{tag}: login accepted an empty email")
        pg.fill("#email", "dr.patel@example.com")
        pg.check("input[value=clinician]", force=True)
        pg.click("button[type=submit]")
        pg.wait_for_url(base + "/")
        pg.wait_for_timeout(2500)
        check_text(pg, f"{tag} clinician")
        pg.screenshot(path=f"data/shots/audit-{tag}-clinician.png", full_page=True)

        if tag == "desk":
            # report
            pg.click("#btn-report")
            pg.wait_for_function("!document.querySelector('#btn-report').disabled", timeout=90000)
            pg.wait_for_timeout(500)
            rep = pg.inner_text("#rep-neuro")
            if len(rep) < 200:
                problems.append("report: neurologist report looks empty")
            pg.click("#tab-patient")
            if len(pg.inner_text("#rep-patient")) < 100:
                problems.append("report: patient summary looks empty")
            if "--live" in sys.argv:  # sends a real iMessage when Photon is running
                pg.click("#btn-test-msg")
                pg.wait_for_timeout(3000)
                print("test message status:", pg.inner_text("#msg-status"))
            # record card
            if "finchnode" not in pg.inner_text("section.finch").lower():
                problems.append("FinchNode label missing on patient record")
            check_text(pg, "desk clinician after actions")

        # caregiver view
        pg.goto(base + "/caregiver")
        pg.wait_for_timeout(2000)
        check_text(pg, f"{tag} caregiver (as clinician)")
        pg.screenshot(path=f"data/shots/audit-{tag}-caregiver.png", full_page=True)

        # sign out -> sign in as caregiver -> clinician view must redirect
        pg.click("text=Sign out")
        pg.wait_for_url(base + "/login")
        pg.fill("#email", "family@example.com")
        pg.check("input[value=caregiver]", force=True)
        pg.click("button[type=submit]")
        pg.wait_for_url(base + "/caregiver")
        pg.goto(base + "/")
        if not pg.url.endswith("/caregiver"):
            problems.append(f"{tag}: caregiver could open the clinician view")
        pg.wait_for_timeout(1500)
        if pg.locator('nav.views a[href="/"]').count():
            problems.append(f"{tag}: caregiver sees a Clinician link")
        check_text(pg, f"{tag} caregiver")
        if errs:
            problems.append(f"{tag}: console/page errors: {errs[:3]}")
        ctx.close()
    b.close()

print("\nAUDIT:", "no problems found" if not problems else f"{len(problems)} problem(s)")
for x in problems:
    print(" -", x)
