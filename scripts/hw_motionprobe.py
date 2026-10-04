"""Silent: is accel event rate motion-gated? Hold device still, then wave."""
import time
from freewili import FreeWili
from freewili.types import EventType
ts = []
def cb(et, f, d):
    if et == EventType.Accel: ts.append((time.perf_counter(), f.timestamp, d.x, d.y, d.z))
with FreeWili.find_first().unwrap() as dev:
    dev.set_event_callback(cb)
    dev.show_text_display("HOLD IN HAND\nkeep still")
    time.sleep(4)
    dev.enable_accel_events(True, 5)
    for phase, secs in (("hold-still", 5), ("wave", 6)):
        if phase == "wave": dev.show_text_display("WAVE\ngently")
        ts.clear(); end = time.perf_counter() + secs
        while time.perf_counter() < end: dev.process_events()
        n = len(ts)
        import statistics as s
        sd = s.pstdev([r[2] for r in ts]) if n > 2 else 0
        print(f"{phase}: {n} events in {secs}s = {n/secs:.1f}/s, x sd {sd:.0f} counts", flush=True)
    dev.enable_accel_events(False)
    dev.show_text_display("Thanks!\nput it down")
