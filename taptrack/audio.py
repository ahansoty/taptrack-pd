"""Spoken instructions: device .wav files (ElevenLabs, see scripts/make_audio.py) with
laptop playback as fallback (local ElevenLabs .wav via winsound, else Windows SAPI TTS)."""
from __future__ import annotations

import logging
import math
import platform
import struct
import subprocess
import threading
import wave
from pathlib import Path

from . import config

log = logging.getLogger("taptrack.audio")

# 8.3 names on the device -> spoken text
PROMPTS = {
    "welcome.wav": "Time for your one minute check. Press blue to begin.",
    "flip.wav": "Flip your hand, palm up, palm down, fast. Press blue to start.",
    "tremor.wav": "Rest your arm and hold still. Press blue to start.",
    "taps.wav": "Tap yellow, then green, as fast as you can. Press blue to start.",
    "voice.wav": "Take a breath and say ahhh. Press blue to start.",
    "done.wav": "All done. Your score is",
    "dose.wav": "Dose logged.",
}
BEEPS = {"beep.wav": (880, 0.15), "go.wav": (1320, 0.25), "end.wav": (660, 0.35)}

OUT_DIR = config.AUDIO_DIR / "out"     # files uploaded to the device (scaled to VOLUME)
SRC_DIR = config.AUDIO_DIR / "src"     # full-level originals (ElevenLabs / SAPI / generated beeps)


def make_beep(path: Path, freq: int, seconds: float, rate: int | None = None):
    rate = rate or config.FW_WAV_RATE
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        fade = int(rate * 0.01)
        frames = []
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade) if fade else 1.0
            frames.append(struct.pack("<h", int(14000 * env * math.sin(2 * math.pi * freq * i / rate))))
        w.writeframes(b"".join(frames))


def scale_wav(src: Path, dst: Path, volume: float):
    """Copy a 16-bit mono wav at a lower level (the device has no volume control)."""
    import array

    with wave.open(str(src)) as r:
        params, frames = r.getparams(), r.readframes(r.getnframes())
    a = array.array("h", frames)
    for i, v in enumerate(a):
        a[i] = int(v * volume)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as w:
        w.setparams(params)
        w.writeframes(a.tobytes())


def apply_volume(volume: float | None = None) -> list[Path]:
    """Write every source wav into OUT_DIR at the configured volume."""
    volume = config.VOLUME if volume is None else volume
    out = []
    for src in sorted(SRC_DIR.glob("*.wav")):
        dst = OUT_DIR / src.name
        scale_wav(src, dst, volume)
        out.append(dst)
    return out


def ensure_beeps() -> dict[str, Path]:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, (f, s) in BEEPS.items():
        src = SRC_DIR / name
        if not src.exists():
            make_beep(src, f, s)
        dst = OUT_DIR / name
        if not dst.exists():
            scale_wav(src, dst, config.VOLUME)
        out[name] = dst
    return out


def local_wav(name: str) -> Path | None:
    p = OUT_DIR / name
    return p if p.exists() else None


def play_local(name: str | None = None, text: str | None = None):
    """Non-blocking laptop playback: ElevenLabs/beep wav if present, else SAPI TTS."""
    def run():
        try:
            p = local_wav(name) if name else None
            if p and platform.system() == "Windows":
                import winsound
                winsound.PlaySound(str(p), winsound.SND_FILENAME)
            elif text and platform.system() == "Windows":
                safe = text.replace("'", "''")
                subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Add-Type -AssemblyName System.Speech; "
                                f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"],
                               capture_output=True, timeout=30)
        except Exception as ex:
            log.warning("laptop audio failed: %s", ex)
    if config.LAPTOP_AUDIO and not config.QUIET:
        threading.Thread(target=run, daemon=True).start()
