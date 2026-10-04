"""Environment-driven configuration. Every integration is off unless its env var is set."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
AUDIO_DIR = ROOT / "audio"

DATABASE_URL = env("DATABASE_URL")
SQLITE_PATH = Path(env("SQLITE_PATH", str(DATA_DIR / "taptrack.db")))

DEMO_MODE = _flag("DEMO_MODE")
# Run the check without waiting for blue presses between tests (useful for demos / tests).
CHECK_AUTO_ADVANCE = _flag("CHECK_AUTO_ADVANCE")
# Set to false to never touch the hardware (dashboard + synthetic only).
USE_DEVICE = _flag("USE_DEVICE", True)

# Measured in HARDWARE_NOTES.md: 5 ms requested interval -> ~79 Hz real.
ACCEL_INTERVAL_MS = int(env("ACCEL_INTERVAL_MS", "5"))
COUNTS_PER_G = float(env("COUNTS_PER_G", "16384"))
MIC_RATE_HZ = float(env("MIC_RATE_HZ", "8000"))
FW_WAV_RATE = int(env("FW_WAV_RATE", "16000"))
# Speak instructions on the laptop when the device can't play them.
LAPTOP_AUDIO = _flag("LAPTOP_AUDIO", True)
# Mute every sound (wrist and laptop), e.g. in a library. Screen + LEDs still work.
QUIET = _flag("QUIET")
# Seconds between passive tremor samples while idle.
PASSIVE_PERIOD_S = float(env("PASSIVE_PERIOD_S", "60"))

PATIENT_ID = env("PATIENT_ID", "demo-patient")
PATIENT_NAME = env("PATIENT_NAME", "Pat Morgan")
# Levodopa schedule (24 h clock); FinchNode can override when it has a levodopa order.
DOSE_TIMES = [t.strip() for t in env("DOSE_TIMES", "08:00,12:00,16:00,20:00").split(",") if t.strip()]
# Expected check windows (local time). A window with no check within +/-45 min is "missed".
CHECK_TIMES = [t.strip() for t in env(
    "CHECK_TIMES", "08:45,10:00,11:15,12:45,14:00,15:15,16:45,18:00,19:15,20:45").split(",") if t.strip()]

FINCHNODE_BASE_URL = env("FINCHNODE_BASE_URL", "https://api.finchnode.com/demo/v1")
FINCHNODE_API_KEY = env("FINCHNODE_API_KEY")
FINCHNODE_PATIENT_ID = env("FINCHNODE_PATIENT_ID", "patient-demo-001")
FINCHNODE_ENABLED = _flag("FINCHNODE_ENABLED", True)

GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-2.5-flash")

ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

HOST = env("HOST", "127.0.0.1")
PORT = int(env("PORT", "8000"))


def features() -> dict:
    return {
        "timescale": bool(DATABASE_URL),
        "finchnode": FINCHNODE_ENABLED and bool(FINCHNODE_BASE_URL),
        "finchnode_mode": "sandbox" if FINCHNODE_API_KEY else "public demo",
        "gemini": bool(GEMINI_API_KEY),
        "elevenlabs": bool(ELEVENLABS_API_KEY),
        "demo_mode": DEMO_MODE,
        "quiet": QUIET,
    }
