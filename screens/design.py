"""FREE-WILi screen designs (320x240, verified in HARDWARE_NOTES.md).

Each screen is one SVG frame (importable into Figma as an editable frame of the same
name). They render to PNG with headless Chromium, so Figma and the wrist match.
If FIGMA_TOKEN + FIGMA_FILE_KEY are set, scripts/figma_sync.py replaces these PNGs with the
frames exported from Figma.

    python screens/design.py          # writes screens/svg, screens/png, screens/contact_sheet.png
    python screens/design.py --fwi    # also converts to .fwi (after the contact sheet is approved)

Rules: no pure black (#000 is transparent on the device), one idea per screen, a word
always accompanies color, very large type. Theme "clinical" (default): cool off-white, navy ink,
teal accent, Inter, soft cards. --theme=warm|editorial renders the alternatives.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SVG_DIR, PNG_DIR, FWI_DIR = HERE / "svg", HERE / "png", HERE / "fwi"
W, H = 320, 240

# Palette + type from ahansoty.github.io: warm paper, ink, rust signal; Instrument Serif /
# Newsreader / IBM Plex Mono. Matches the web dashboard tokens.
CREAM = "#F6F1E8"      # --ground
CREAM_2 = "#ECE5D8"    # --sunk
BROWN = "#1F1B17"      # --ink (non-zero in RGB565, never pure black)
BROWN_2 = "#514840"    # --body
MUTED = "#948877"      # --muted
RULE = "#DFD6C6"       # --rule
ORANGE = "#B9451F"     # --signal (rust)
GOOD, FAIR, LOW = "#3E7B57", "#A86B12", "#9E2B25"
BTN = {"gray": "#948877", "yellow": "#D4A21A", "green": "#3E9461", "blue": "#3A6EB5", "red": "#B83A2E"}
# physical buttons, left to right under the screen (verified)
BTN_X = {"gray": 32, "yellow": 96, "green": 160, "blue": 224, "red": 288}
SERIF = "'Instrument Serif', Georgia, serif"
TEXT = "Newsreader, Georgia, serif"
MONO = "'IBM Plex Mono', Consolas, monospace"
FONT = TEXT
FONTS_CSS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600"
             "&family=Instrument+Serif&family=Newsreader:opsz,wght@6..72,400;6..72,500"
             "&family=Inter:wght@400;500;600;700&display=swap")
HEAD_WEIGHT = 400      # headline weight
HEAD_WIDTH = 0.47      # average glyph width / size, for fitting headlines
LABEL_SPACING = 1.8
CARD = False           # soft panel behind the status block
RADIUS = 0

SANS = "Inter, 'Segoe UI', Arial, sans-serif"
THEMES = {
    "editorial": {},
    "clinical": dict(CREAM="#F7F8FA", CREAM_2="#EBEFF5", BROWN="#132238", BROWN_2="#3E4C63", MUTED="#5F6B80",
                     RULE="#D5DBE5", ORANGE="#0F766E", GOOD="#1F7A4D", FAIR="#9A6400", LOW="#B42318",
                     SERIF=SANS, TEXT=SANS, MONO=SANS, FONT=SANS, HEAD_WEIGHT=600, HEAD_WIDTH=0.56,
                     LABEL_SPACING=1.1, CARD=True, RADIUS=10),
    "warm": dict(CREAM="#FAF7F2", CREAM_2="#F0E9DE", BROWN="#1F1B17", BROWN_2="#4A4038", MUTED="#74685B",
                 RULE="#E2D8C8", ORANGE="#B9451F", GOOD="#2F7350", FAIR="#93600E", LOW="#A3291F",
                 SERIF=SANS, TEXT=SANS, MONO=SANS, FONT=SANS, HEAD_WEIGHT=600, HEAD_WIDTH=0.56,
                 LABEL_SPACING=1.1, CARD=True, RADIUS=10),
}


def apply_theme(name: str):
    globals().update(THEMES[name])


DEFAULT_THEME = "clinical"  # chosen 2026-10-03 (A Clinical)

# 8.3 names on the device
SCREENS = ["home_n", "home_g", "home_y", "home_r", "home_due", "home_med",
           "ready", "flip", "tremor", "taps", "voice", "res_g", "res_y", "res_r"]


def svg(body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<title>{title}</title><rect width="{W}" height="{H}" fill="{CREAM}"/>{body}</svg>')


def text(x, y, s, size, weight=400, fill=None, anchor="middle", spacing=0, family=None):
    fill = fill or BROWN
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    fam = (family or TEXT).replace('"', "'")
    return (f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}"{ls}>{s}</text>')


def serif(x, y, s, size, fill=None, anchor="start"):
    return text(x, y, s, size, HEAD_WEIGHT, fill or BROWN, anchor, -0.3 if HEAD_WEIGHT == 400 else -0.5, SERIF)


def mono(x, y, s, size=11, fill=None, anchor="start", weight=500):
    return text(x, y, s.upper(), size, max(weight, 600) if CARD else weight, fill or MUTED, anchor, LABEL_SPACING, MONO)


def topbar(left: str, right: str = "") -> str:
    """Mono kicker over a hairline rule, like the portfolio masthead."""
    return (f'<circle cx="19" cy="20" r="3.5" fill="{ORANGE}"/>' + mono(30, 24, left, 11, BROWN_2)
            + (mono(W - 14, 24, right, 11, MUTED, "end") if right else "")
            + f'<rect x="14" y="34" width="{W - 28}" height="1" fill="{RULE}"/>')


def legend(labels: dict[str, str]) -> str:
    """Labels at the physical button positions with a square color chip, along the bottom edge."""
    out = f'<rect x="14" y="200" width="{W - 28}" height="1" fill="{RULE}"/>'
    for color, label in labels.items():
        x = BTN_X[color]
        out += f'<rect x="{x - 5}" y="224" width="10" height="10" fill="{BTN[color]}"/>'
        out += mono(x, 216, label, 11, BROWN_2, "middle", 600)
    return out


def fit(word: str, max_w: float, max_size: int) -> int:
    return int(min(max_size, max_w / (0.6 * max(len(word), 1))))


def status_table():
    return {
    # name: (rule color, small label, status word, footnote)
    "home_n": (BROWN_2, "STATUS", "Ready", "Press Check to start"),
    "home_g": (GOOD, "LAST CHECK", "Good", "Near your usual"),
    "home_y": (FAIR, "LAST CHECK", "Lower than usual", ""),
    "home_r": (LOW, "LAST CHECK", "Much lower", "Care team notified"),
    "home_due": (ORANGE, "REMINDER", "Check due", "Press Check to start"),
    "home_med": (BTN["blue"], "MEDICATION", "Dose logged", "Thank you"),
    }


def fit_serif(word: str, max_w: float, max_size: int) -> int:
    return int(min(max_size, max_w / (HEAD_WIDTH * max(len(word), 1))))


def status_block(y, color, label, word, foot, max_size=60):
    size = fit_serif(word, 280 if CARD else 288, max_size if not CARD else 50)
    ch = 196 - y + 6
    out = (f'<clipPath id="card"><rect x="8" y="{y - 20}" width="{W - 16}" height="{ch}" rx="{RADIUS}"/></clipPath>'
           f'<g clip-path="url(#card)"><rect x="8" y="{y - 20}" width="{W - 16}" height="{ch}" fill="{CREAM_2}"/>'
           f'<rect x="8" y="{y - 20}" width="6" height="{ch}" fill="{color}"/></g>') if CARD else ""
    x0 = 24 if CARD else 16
    out += mono(x0, y, label, 11, MUTED)
    if size < 40 and " " in word:  # two lines rather than small type
        a, b = word.rsplit(" ", 1)
        size = min(46, fit_serif(a, 288, 46))
        out += serif(x0, y + size - 2, a, size) + serif(x0, y + 2 * size - 8, b, size)
        rule_y = y + 2 * size + 2
    else:
        out += serif(x0, y + size - 4, word, size)
        rule_y = y + size + 8
    if not CARD:
        out += f'<rect x="16" y="{rule_y}" width="48" height="4" fill="{color}"/>'
    if foot:
        out += text(x0, rule_y + (22 if CARD else 28), foot, 17, 400, BROWN_2, "start")
    return out


def home(name):
    color, label, word, foot = status_table()[name]
    return svg(topbar("TapTrack PD") + status_block(62, color, label, word, foot)
               + legend({"gray": "BACK", "yellow": "TAP", "green": "TAP", "blue": "CHECK", "red": "MEDS"}), name)


def instruction(name, step, line1, line2, sub, art):
    hs = min(46, fit_serif(max(line1, line2, key=len), 290, 46))
    t = serif(16, 82, line1, hs) + (serif(16, 124, line2, hs) if line2 else "")
    sub_y = 150 if line2 else 112
    return svg(topbar("TapTrack PD", f"Test {step} of 4") + t + text(16, sub_y, sub, 16, 400, BROWN_2, "start")
               + art + legend({"gray": "STOP"}), name)


def line_style():
    return f'fill="none" stroke="{BROWN}" stroke-width="3" stroke-linecap="square" stroke-linejoin="miter"'


def acc_style():
    return f'fill="none" stroke="{ORANGE}" stroke-width="3" stroke-linecap="square" stroke-linejoin="miter"'


def art_flip():
    # forearm seen end-on: a flat bar, palm up (solid) and palm down (outline), rust arc between
    return (f'<rect x="196" y="128" width="96" height="12" fill="{BROWN}"/>'
            + mono(188, 138, "palm up", 9, MUTED, "end")
            + f'<rect x="197.5" y="165.5" width="93" height="9" fill="none" stroke="{BROWN}" stroke-width="3"/>'
            + mono(188, 174, "palm down", 9, MUTED, "end")
            + f'<path d="M298,134 C314,140 314,164 298,170" {acc_style()}/><path d="M306,165 l-8,5 l7,6" {acc_style()}/>')


def art_tremor():
    # a flat level line with a tolerance band
    return (f'<rect x="16" y="150" width="288" height="26" fill="{CREAM_2}"/>'
            f'<path d="M16,163 H304" {line_style()}/>'
            f'<path d="M16,150 H304 M16,176 H304" fill="none" stroke="{RULE}" stroke-width="1"/>'
            + mono(304, 192, "20 seconds", 9, MUTED, "end"))


def art_taps():
    y = 178
    yx, gx = BTN_X["yellow"], BTN_X["green"]
    return (f'<rect x="{yx - 13}" y="{y - 13}" width="26" height="26" fill="{BTN["yellow"]}"/>'
            f'<rect x="{gx - 13}" y="{y - 13}" width="26" height="26" fill="{BTN["green"]}"/>'
            + mono(yx, y + 5, "1", 14, CREAM, "middle", 600) + mono(gx, y + 5, "2", 14, CREAM, "middle", 600)
            + f'<path d="M{yx + 22},{y} H{gx - 22}" {acc_style()}/><path d="M{gx - 29},{y - 6} l7,6 l-7,6" {acc_style()}/>'
            + mono(304, y + 5, "10 seconds", 9, MUTED, "end"))


def art_voice():
    # level meter bars, steady
    bars = "".join(f'<rect x="{16 + i * 12}" y="{170 - h}" width="7" height="{h}" fill="{BROWN if i % 6 else ORANGE}"/>'
                   for i, h in enumerate([10, 16, 22, 26, 28, 28, 28, 27, 28, 28, 28, 27, 28, 26, 22, 16, 10]))
    return bars + mono(304, 166, "5 seconds", 9, MUTED, "end")


def ready():
    body = (serif(16, 92, "Get ready", 56)
            + text(16, 124, "The next test starts when", 17, 400, BROWN_2, "start")
            + text(16, 146, "you press Start.", 17, 400, BROWN_2, "start")
            + f'<path d="M{BTN_X["blue"]},150 V188" {acc_style()}/><path d="M{BTN_X["blue"] - 7},181 l7,7 l7,-7" {acc_style()}/>')
    return svg(topbar("TapTrack PD") + body + legend({"gray": "STOP", "blue": "START"}), "ready")


def result(name, color, word, foot):
    return svg(topbar("TapTrack PD", "Check complete") + status_block(62, color, "Result", word, "")
               + f'<rect x="14" y="200" width="{W - 28}" height="1" fill="{RULE}"/>'
               + text(16, 226, foot, 16, 400, BROWN_2, "start"), name)


def build_svgs() -> dict[str, str]:
    out = {n: home(n) for n in status_table()}
    out["ready"] = ready()
    out["flip"] = instruction("flip", 1, "Flip your hand", "", "Palm up, palm down. Fast and full.", art_flip())
    out["tremor"] = instruction("tremor", 2, "Hold still", "", "Rest your arm. Keep the wrist calm.", art_tremor())
    out["taps"] = instruction("taps", 3, "Tap yellow,", "then green", "Alternate, as fast as you can.", art_taps())
    out["voice"] = instruction("voice", 4, "Say “ahhh”", "", "One steady breath, clear and loud.", art_voice())
    out["res_g"] = result("res_g", GOOD, "Good", "Your score was spoken aloud.")
    out["res_y"] = result("res_y", FAIR, "Lower than usual", "Your score was spoken aloud.")
    out["res_r"] = result("res_r", LOW, "Much lower", "Score spoken. Care team notified.")
    return out


def render_pngs(svgs: dict[str, str]):
    from playwright.sync_api import sync_playwright

    SVG_DIR.mkdir(exist_ok=True)
    PNG_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for name, s in svgs.items():
            (SVG_DIR / f"{name}.svg").write_text(s, encoding="utf-8")
            pg.set_content(f'<html><head><link rel="stylesheet" href="{FONTS_CSS}"></head>'
                           f'<body style="margin:0;background:{CREAM}">{s}</body></html>', wait_until="networkidle")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(80)
            pg.screenshot(path=str(PNG_DIR / f"{name}.png"), clip={"x": 0, "y": 0, "width": W, "height": H})
        b.close()


def no_black(png: Path) -> Path:
    """Lift any pixel that would quantize to RGB565 zero (transparent) to the darkest visible value."""
    from PIL import Image

    im = Image.open(png).convert("RGB")
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b = px[x, y]
            if int(r / 255 * 31) == 0 and int(g / 255 * 63) == 0 and int(b / 255 * 31) == 0:
                px[x, y] = (9, 5, 9)
    im.save(png)
    return png


def contact_sheet(path=HERE / "contact_sheet.png", scale=2):
    from PIL import Image, ImageDraw, ImageFont

    cols, pad, lab = 4, 24, 34
    rows = (len(SCREENS) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (W * scale + pad) + pad, rows * (H * scale + pad + lab) + pad + 50), (238, 236, 230))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22)
    d.text((pad, 14), "TapTrack PD · FREE-WILi screens (320x240, shown at 2x)", font=f, fill=(30, 30, 30))
    for i, name in enumerate(SCREENS):
        im = Image.open(PNG_DIR / f"{name}.png").resize((W * scale, H * scale), Image.NEAREST)
        x = pad + (i % cols) * (W * scale + pad)
        y = 50 + pad + (i // cols) * (H * scale + pad + lab)
        sheet.paste(im, (x, y + lab))
        d.text((x, y + 4), f"{name}.fwi", font=f, fill=(50, 50, 50))
    sheet.save(path)
    return path


def compare_themes(names=("clinical", "warm", "editorial"), screens=("home_y", "taps", "res_g"),
                   path=HERE / "themes.png", scale=2):
    """Render a few screens in each theme side by side for choosing a direction."""
    import importlib
    from PIL import Image, ImageDraw, ImageFont
    from playwright.sync_api import sync_playwright

    mod = importlib.import_module(__name__) if __name__ != "__main__" else sys.modules[__name__]
    pad, lab = 24, 40
    sheet = Image.new("RGB", (pad + len(screens) * (W * scale + pad), 60 + len(names) * (H * scale + pad + lab)), (236, 234, 229))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 26)
    d.text((pad, 16), "Wrist screen directions (pick one)", font=f, fill=(30, 30, 30))
    base = {k: getattr(mod, k) for k in THEMES["clinical"]}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        for r, name in enumerate(names):
            globals().update(base)
            apply_theme(name)
            svgs = build_svgs()
            y = 60 + r * (H * scale + pad + lab)
            d.text((pad, y + 4), {"clinical": "A  Clinical", "warm": "B  Warm professional", "editorial": "C  Editorial (current)"}[name], font=f, fill=(30, 30, 30))
            for c, sc in enumerate(screens):
                pg.set_content(f'<html><head><link rel="stylesheet" href="{FONTS_CSS}"></head>'
                               f'<body style="margin:0">{svgs[sc]}</body></html>', wait_until="networkidle")
                pg.evaluate("document.fonts.ready")
                pg.wait_for_timeout(60)
                tmp = HERE / "_tmp.png"
                pg.screenshot(path=str(tmp), clip={"x": 0, "y": 0, "width": W, "height": H})
                im = Image.open(tmp).resize((W * scale, H * scale), Image.LANCZOS)
                sheet.paste(im, (pad + c * (W * scale + pad), y + lab))
        b.close()
    (HERE / "_tmp.png").unlink(missing_ok=True)
    globals().update(base)
    sheet.save(path)
    return path


def to_fwi():
    from freewili import image as fwimg
    import contextlib
    import io

    FWI_DIR.mkdir(exist_ok=True)
    for name in SCREENS:
        png = no_black(PNG_DIR / f"{name}.png")
        with contextlib.redirect_stdout(io.StringIO()):  # convert() prints its header
            r = fwimg.convert(png, FWI_DIR / f"{name}.fwi")
        if r.is_err():
            raise RuntimeError(r.err_value)
    return sorted(FWI_DIR.glob("*.fwi"))


if __name__ == "__main__":
    if "--compare" in sys.argv:
        print("themes:", compare_themes())
        raise SystemExit
    apply_theme(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--theme=")), DEFAULT_THEME))
    if "--from-figma" not in sys.argv:
        render_pngs(build_svgs())
    print("contact sheet:", contact_sheet())
    if "--fwi" in sys.argv:
        print("fwi:", [p.name for p in to_fwi()])
