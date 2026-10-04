"""Load 14 days of synthetic levodopa/wearing-off data into storage and print summary stats.

    python scripts/seed.py [--days 14] [--seed 7]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from taptrack import synth  # noqa: E402
from taptrack.storage import get_store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=14)
ap.add_argument("--seed", type=int, default=7)
a = ap.parse_args()
store = get_store()
stats = synth.load_into(store, days=a.days, seed=a.seed)
print(f"storage: {store.kind}")
print(json.dumps(stats, indent=2))
