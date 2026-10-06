"""Button diagnostic: set screen text first, then enable events (the order that works on firmware v54)."""
import time
from freewili import FreeWili
from freewili.types import ButtonData, EventType
COLORS = ("gray", "yellow", "green", "blue", "red")
seq, last = [], {}
def cb(et, frame, data):
    if et == EventType.Button and isinstance(data, ButtonData):
        st = {c: getattr(data, c) for c in COLORS}
        for c in COLORS:
            if st[c] and not last.get(c):
                seq.append(c); print("  pressed", c, "raw", frame.response, flush=True)
        last.update(st)
with FreeWili.find_first().unwrap() as dev:
    dev.set_event_callback(cb)
    dev.show_text_display("Press gray yel\ngrn blue red x2")
    dev.play_audio_file("t8k.wav")
    time.sleep(0.5)
    print("enable", dev.enable_button_events(True, 10), flush=True)
    end = time.perf_counter() + 20
    while time.perf_counter() < end:
        dev.process_events()
    dev.enable_button_events(False)
    print("sequence:", seq)
    print("seen:", sorted(set(seq)), "missing:", sorted(set(COLORS) - set(seq)))
    dev.show_text_display("Thanks")
