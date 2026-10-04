import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# tests never touch hardware, the network, or make sound
os.environ.setdefault("QUIET", "true")
os.environ.setdefault("USE_DEVICE", "false")
os.environ.setdefault("FINCHNODE_ENABLED", "false")
os.environ["GEMINI_API_KEY"] = ""
os.environ["DATABASE_URL"] = ""
