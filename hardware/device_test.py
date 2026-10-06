"""Hardware check for the FREE-WILi used by TapTrack PD.

Run:  python hardware/device_test.py            (full test, prompts appear on the device screen)
      python hardware/device_test.py clip.wav   (also upload and play your own .wav)
Plug in the FREE-WILi by USB first. Press Ctrl+C to stop early.

What it checks:
  1. Device connects
  2. Screen text, LEDs, tone, number speech work
  3. Real accelerometer sample rate at several intervals, measured on both the host
     clock and the device frame timestamps (decides tremor frequency analysis)
  4. Counts per g at rest (device flat on the table)
  5. Button events arrive (press each button)
  6. Audio (mic) events arrive (say "ahhh"), with the effective mic sample rate
  7. .wav upload + playback at several sample rates (generated tones)

Notes from reading freewili 0.0.51 source:
  - send_file(local, target): target is a full device path. A bare "test.wav" lands in
    the root, so we upload to "/sounds/<8.3 name>" (the default FileMap location for .wav).
  - play_audio_file(name) plays from /sounds by name.
  - ResponseFrame.timestamp is a device unix-epoch timestamp in ns.
"""
import math
import struct
import sys
import tempfile
import time
import wave
from collections import defaultdict
from pathlib import Path

from freewili import FreeWili
from freewili.types import AccelData, AudioData, ButtonData, EventType

counts = defaultdict(int)
accel = []  # (host_t, device_ts_ns, x, y, z, g)
last_buttons = {}
pressed_seen = set()
audio_chunks = []  # (host_t, device_ts_ns, n_samples)
audio_samples = []


def on_event(event_type, frame, data):
    counts[event_type] += 1
    now = time.perf_counter()
    ts = getattr(frame, "timestamp", 0)
    if event_type == EventType.Accel and isinstance(data, AccelData):
        accel.append((now, ts, data.x, data.y, data.z, data.g))
    elif event_type == EventType.Button and isinstance(data, ButtonData):
        state = {c: getattr(data, c) for c in ("gray", "yellow", "green", "blue", "red")}
        pressed = [c for c, v in state.items() if v and not last_buttons.get(c)]
        if pressed:
            pressed_seen.update(pressed)
            print(f"  button pressed: {', '.join(pressed)}", flush=True)
        last_buttons.update(state)
    elif event_type == EventType.Audio and isinstance(data, AudioData):
        audio_chunks.append((now, ts, len(data.data)))
        audio_samples.extend(data.data)


def check(label, result):
    ok = result.is_ok()
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + ("" if ok else f": {result.err_value}"), flush=True)
    return ok


def pump(dev, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        dev.process_events()


def rate_from(times):
    if len(times) < 2 or times[-1] == times[0]:
        return 0.0
    return (len(times) - 1) / (times[-1] - times[0])


def make_tone_wav(path, rate, seconds=1.0, freq=660):
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
        )
        w.writeframes(frames)


def main():
    found = FreeWili.find_first()
    if found.is_err():
        print("No FREE-WILi found. Check the USB cable and try another port.")
        return
    with found.unwrap() as dev:
        print(f"Connected: {dev}\n", flush=True)
        dev.set_event_callback(on_event)

        # 2. Outputs
        check("show_text_display", dev.show_text_display("TapTrack PD\nHW test"))
        led_ok = all(dev.set_board_leds(io, 0, 60, 0).is_ok() for io in range(7))
        print(f"[{'OK' if led_ok else 'FAIL'}] set_board_leds x7 (green, check visually)")
        check("play_audio_tone", dev.play_audio_tone(880, 0.3, 0.5))
        time.sleep(0.5)
        check("play_audio_number_as_speech (42)", dev.play_audio_number_as_speech(42))
        time.sleep(2)

        # 3. Accelerometer rate
        dev.show_text_display("Keep still\nflat on table")
        print("\nAccelerometer rate test (keep device still, flat on the table):", flush=True)
        rest = None
        for interval in (100, 50, 20, 10, 5):
            accel.clear()
            r = dev.enable_accel_events(True, interval)
            if r.is_err():
                print(f"  interval {interval} ms: enable failed: {r.err_value}")
                continue
            pump(dev, 3)
            dev.enable_accel_events(False)
            pump(dev, 0.3)
            n = len(accel)
            host = rate_from([a[0] for a in accel])
            dts = [a[1] / 1e9 for a in accel if a[1]]
            devr = rate_from(dts)
            print(f"  interval {interval:>3} ms -> {n} samples, host ~{host:.1f} Hz, device-clock ~{devr:.1f} Hz", flush=True)
            if n > 10 and interval == 20:
                rest = list(accel)
        if rest:
            xs = [a[2] for a in rest]; ys = [a[3] for a in rest]; zs = [a[4] for a in rest]
            mean = lambda v: sum(v) / len(v)
            mag = math.sqrt(mean(xs) ** 2 + mean(ys) ** 2 + mean(zs) ** 2)
            sd = lambda v: (sum((q - mean(v)) ** 2 for q in v) / len(v)) ** 0.5
            print(f"  at rest: mean x={mean(xs):.0f} y={mean(ys):.0f} z={mean(zs):.0f}, |a|={mag:.0f} counts "
                  f"(range {rest[0][5]:g}g) -> ~{mag:.0f} counts/g; noise sd x={sd(xs):.0f} y={sd(ys):.0f} z={sd(zs):.0f}")
        print("  Need >= 40 Hz for tremor frequency; otherwise use tremor strength only.", flush=True)

        # 4. Buttons
        print("\nButton test: press every button (gray, yellow, green, blue, red) within 20 seconds.", flush=True)
        dev.show_text_display("Press every\nbutton")
        dev.play_audio_tone(660, 0.2, 0.5)
        check("enable_button_events", dev.enable_button_events(True, 10))
        end = time.perf_counter() + 20
        while time.perf_counter() < end and len(pressed_seen) < 5:
            dev.process_events()
        dev.enable_button_events(False)
        missing = {"gray", "yellow", "green", "blue", "red"} - pressed_seen
        print(f"  buttons seen: {sorted(pressed_seen)}; missing: {sorted(missing) or 'none'}", flush=True)

        # 5. Audio
        print("\nMic test: say 'ahhh' for 5 seconds (starts at the beep).", flush=True)
        dev.show_text_display("Say ahhh\n5 seconds")
        dev.play_audio_tone(660, 0.2, 0.5)
        time.sleep(0.4)
        audio_samples.clear()
        audio_chunks.clear()
        check("enable_audio_events", dev.enable_audio_events(True))
        pump(dev, 5)
        dev.enable_audio_events(False)
        pump(dev, 0.3)
        if audio_samples:
            rms = (sum(s * s for s in audio_samples) / len(audio_samples)) ** 0.5
            span = audio_chunks[-1][0] - audio_chunks[0][0] if len(audio_chunks) > 1 else 0
            dspan = (audio_chunks[-1][1] - audio_chunks[0][1]) / 1e9 if len(audio_chunks) > 1 else 0
            sizes = sorted({c[2] for c in audio_chunks})
            print(f"  got {len(audio_samples)} samples in {len(audio_chunks)} events (sizes {sizes[:5]}), RMS {rms:.0f}, "
                  f"min {min(audio_samples)} max {max(audio_samples)}")
            if span:
                print(f"  effective rate host ~{len(audio_samples) / span:.0f} samples/s, "
                      f"device-clock ~{(len(audio_samples) / dspan) if dspan else 0:.0f} samples/s; "
                      f"events/s ~{len(audio_chunks) / span:.1f}", flush=True)
            # second-by-second loudness profile
            per = max(1, len(audio_samples) // 5)
            prof = [(sum(s * s for s in audio_samples[i:i + per]) / per) ** 0.5 for i in range(0, per * 5, per)]
            print("  RMS per 1/5 window:", [round(p) for p in prof])
        else:
            print("  no audio samples received")

        # 6. wav upload + playback at several sample rates
        print("\nWAV upload/playback test (listen for a short tone after each upload):", flush=True)
        tmp = Path(tempfile.mkdtemp())
        dev.show_text_display("Audio upload\ntest")
        for rate in (8000, 16000, 22050):
            p = tmp / f"t{rate // 1000}k.wav"
            make_tone_wav(p, rate)
            t0 = time.time()
            if check(f"send_file {p.name} -> /sounds/{p.name} ({p.stat().st_size} B)", dev.send_file(p, f"/sounds/{p.name}")):
                print(f"    upload took {time.time() - t0:.1f} s")
                check(f"play_audio_file {p.name}", dev.play_audio_file(p.name))
                time.sleep(1.8)
        if len(sys.argv) > 1:
            print(f"\nUploading {sys.argv[1]} as /sounds/test.wav")
            if check("send_file", dev.send_file(sys.argv[1], "/sounds/test.wav")):
                check("play_audio_file", dev.play_audio_file("test.wav"))
                time.sleep(4)

        for io in range(7):
            dev.set_board_leds(io, 0, 0, 0)
        dev.show_text_display("HW test done")
        print("\nEvent counts:", {str(k): v for k, v in counts.items()})
        print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
