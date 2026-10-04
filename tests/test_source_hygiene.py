"""Guard against invisible control characters in source files (a stray backspace once broke a regex)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOBS = ["taptrack/*.py", "static/*.js", "static/*.html", "static/*.css", "docs/*.html", "scripts/*.py",
         "agent/*.py", "screens/*.py", "photon/*.mjs"]


def test_no_control_characters():
    bad = []
    for g in GLOBS:
        for f in ROOT.glob(g):
            text = f.read_text(encoding="utf-8")
            if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                bad.append(str(f.relative_to(ROOT)))
    assert not bad, f"control characters in: {bad}"
