"""Probe: do show_text_display / play_audio_file / set_board_leds stop the event stream?"""
import time
from freewili import FreeWili
from freewili.types import EventType
n = {"a": 0}
def cb(et, f, d):
    if et == EventType.Accel: n["a"] += 1
def window(dev, s=1.5):
    n["a"] = 0; end = time.perf_counter() + s
    while time.perf_counter() < end: dev.process_events()
    return n["a"]
with FreeWili.find_first().unwrap() as dev:
    dev.set_event_callback(cb)
    print("enable", dev.enable_accel_events(True, 10))
    print("baseline", window(dev))
    for label, fn in [("leds", lambda: dev.set_board_leds(0, 0, 40, 0)),
                      ("text", lambda: dev.show_text_display("probe")),
                      ("after-text", lambda: None),
                      ("re-enable", lambda: dev.enable_accel_events(True, 10)),
                      ("wav", lambda: dev.play_audio_file("t8k.wav")),
                      ("after-wav", lambda: None),
                      ("re-enable2", lambda: dev.enable_accel_events(True, 10)),
                      ("speech", lambda: dev.play_audio_number_as_speech(7)),
                      ("after-speech", lambda: None)]:
        r = fn()
        print(f"{label:>12}: {r}  -> {window(dev)} accel events/1.5s", flush=True)
    dev.enable_accel_events(False)
