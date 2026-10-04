"""Pull the wrist screens from Figma and rebuild the .fwi files.

Workflow:
  1. python screens/design.py           -> screens/svg/*.svg (one per screen)
  2. In Figma: File > Import, select screens/svg/*.svg. Each becomes a 320x240 frame named
     after the screen (home_g, flip, ...). Edit freely; keep the frame names and size.
  3. Set FIGMA_TOKEN (Figma > Settings > Security > Personal access tokens, scope file_content:read)
     and FIGMA_FILE_KEY (the part after /design/ in the file URL) in .env.
  4. python scripts/figma_sync.py       -> exports each frame as PNG, writes screens/png, builds .fwi
     The bridge uploads only screens whose content changed on next start.

Uses the Figma REST API: GET /v1/files/:key (find frames) and GET /v1/images/:key (render PNGs).
"""
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "screens"))
from taptrack.config import env  # noqa: E402
import design  # noqa: E402

API = "https://api.figma.com/v1"


def main() -> int:
    token, key = env("FIGMA_TOKEN"), env("FIGMA_FILE_KEY")
    if not token or not key:
        print("FIGMA_TOKEN / FIGMA_FILE_KEY not set: keeping the locally rendered screens.")
        return 1
    h = {"X-Figma-Token": token}
    with httpx.Client(timeout=60, headers=h) as c:
        r = c.get(f"{API}/files/{key}", params={"depth": 3})
        r.raise_for_status()
        frames = {}

        def walk(node):
            if node.get("type") in ("FRAME", "COMPONENT") and node.get("name") in design.SCREENS:
                frames.setdefault(node["name"], node["id"])
            for ch in node.get("children", []) or []:
                walk(ch)

        walk(r.json()["document"])
        missing = [s for s in design.SCREENS if s not in frames]
        print(f"found {len(frames)} frames in Figma; using local design for: {missing or 'none'}")
        if not frames:
            return 1
        r = c.get(f"{API}/images/{key}", params={"ids": ",".join(frames.values()), "format": "png", "scale": 1})
        r.raise_for_status()
        urls = r.json()["images"]
        design.PNG_DIR.mkdir(exist_ok=True)
        for name, node_id in frames.items():
            url = urls.get(node_id)
            if not url:
                print(f"  {name}: Figma returned no image")
                continue
            png = design.PNG_DIR / f"{name}.png"
            png.write_bytes(httpx.get(url, timeout=60).content)
            from PIL import Image

            im = Image.open(png)
            if im.size != (design.W, design.H):
                im.convert("RGB").resize((design.W, design.H), Image.LANCZOS).save(png)
                print(f"  {name}: resized {im.size} -> 320x240")
            print(f"  {name}: exported")
    design.contact_sheet()
    print("fwi:", [p.name for p in design.to_fwi()])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
