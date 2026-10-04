"""Build screens/fwi from screens/png and upload any changed screens to the FREE-WILi (silent).

    python scripts/upload_screens.py [--show NAME]
Uploads are skipped for screens whose content hash is already recorded on this device.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "screens"))
import design  # noqa: E402
from taptrack.bridge import Bridge  # noqa: E402
from taptrack.device import FreeWiliDevice  # noqa: E402
from taptrack.storage import get_store  # noqa: E402

design.to_fwi()
dev = FreeWiliDevice()
if not dev.open():
    sys.exit("No FREE-WILi found")
b = Bridge(get_store(), device=dev)
t = time.time()
b.device = dev
b._sync_screens()
print(f"screens on device: {sorted(dev.images)} ({time.time() - t:.0f} s)")
name = sys.argv[sys.argv.index("--show") + 1] if "--show" in sys.argv else "home_n"
print("show", name, dev.show_image(name))
dev.dev.close()
