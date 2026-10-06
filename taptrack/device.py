"""FREE-WILi device wrapper + a simulated device with the same interface.

Only the bridge thread touches a device. Every library call returns a Result; failures are
logged and returned as False, never raised. A serial exception marks the device
disconnected so the bridge can fall back to DEMO_MODE replay.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque

import numpy as np

from . import config

log = logging.getLogger("taptrack.device")
COLORS = ("gray", "yellow", "green", "blue", "red")


class BaseDevice:
    name = "base"

    def __init__(self):
        self.connected = False
        self.accel = deque(maxlen=20000)  # (host_t, dev_raw, x_g, y_g, z_g)
        self.audio = []                   # raw mic samples while audio streaming
        self.presses = deque(maxlen=500)  # (host_t, color)
        self.on_press = None              # callback(color) for immediate actions
        self._buttons = {}
        self.buttons_on = False
        self.sounds: set[str] = set()     # .wav names present on the device
        self.images: set[str] = set()     # screen names (.fwi) present on the device
        self.current_screen = None

    # outputs -------------------------------------------------------------
    def show(self, text: str) -> bool: return True
    def leds(self, rgb) -> bool: return True
    def say_number(self, n: int) -> bool: return True
    def play(self, name: str) -> bool: return False
    def upload(self, local_path, name: str) -> bool: return False
    def show_image(self, name: str) -> bool: return False
    def upload_image(self, local_path, name: str) -> bool: return False
    def led(self, io: int, rgb) -> bool: return True

    def screen(self, name: str, fallback_text: str) -> bool:
        """Full-screen image if uploaded, else the text fallback."""
        self.current_screen = name
        if name in self.images and self.show_image(name):
            return True
        return self.show(fallback_text)

    def progress(self, frac: float, rgb, lit: int | None = None) -> int:
        """7 board LEDs as a progress bar. Only changes the LEDs that differ (serial is slow)."""
        n = max(0, min(7, int(round(frac * 7))))
        prev = -1 if lit is None else lit
        if n == prev:
            return n
        for io in range(7):
            on = io < n
            was = prev >= 0 and io < prev
            if prev < 0 or on != was:
                self.led(io, rgb if on else (0, 0, 0))
        return n

    # inputs --------------------------------------------------------------
    def stream_accel(self, on: bool) -> bool: return True
    def stream_buttons(self, on: bool) -> bool:
        self.buttons_on = on
        return True
    def stream_audio(self, on: bool) -> bool: return True
    def pump(self, seconds: float = 0.02): time.sleep(seconds)
    def open(self) -> bool:
        self.connected = True
        return True
    def close(self): self.connected = False

    def _press(self, color: str, t: float | None = None):
        t = t or time.perf_counter()
        self.presses.append((t, color))
        if self.on_press:
            try:
                self.on_press(color)
            except Exception:
                log.exception("on_press handler failed")

    def accel_window(self, seconds: float):
        """Last `seconds` of accel as (t_seconds, xyz_g) using device timestamps when sane."""
        now = time.perf_counter()
        rows = [r for r in list(self.accel) if r[0] >= now - seconds]
        return accel_arrays(rows)


def accel_arrays(rows):
    if not rows:
        return np.zeros(0), np.zeros((0, 3))
    a = np.array(rows, dtype=float)
    host, dev = a[:, 0], a[:, 1]
    t = host
    if np.all(dev > 0) and len(a) > 4 and host[-1] > host[0]:
        span_h = host[-1] - host[0]
        # library says ns, firmware v54 sends us; pick the scale that matches the host clock
        for scale in (1e6, 1e9, 1e3):
            span_d = (dev[-1] - dev[0]) / scale
            if 0.7 < span_d / span_h < 1.4 and np.all(np.diff(dev) >= 0):
                t = (dev - dev[0]) / scale + host[0]
                break
    return regularize(t), a[:, 2:5]


def regularize(t, min_rate=40.0, max_cv=0.5):
    """USB delivers events in bursts, so arrival times cluster. When the stream is clearly continuous
    (>= 40 Hz overall, i.e. worn and moving) but the spacing is bursty, the device sampled on a fixed
    interval: spread the samples evenly over the span. Bursty timing otherwise injects a fake rhythm
    at the burst rate into tremor and flip signals. Slow (motion-gated) streams are left alone."""
    t = np.asarray(t, dtype=float)
    if len(t) < 20 or t[-1] <= t[0]:
        return t
    dt = np.diff(t)
    rate = (len(t) - 1) / (t[-1] - t[0])
    if rate >= min_rate and dt.mean() > 0 and dt.std() / dt.mean() > max_cv:
        return np.linspace(t[0], t[-1], len(t))
    return t


class FreeWiliDevice(BaseDevice):
    name = "freewili"

    def __init__(self):
        super().__init__()
        self.dev = None
        self._accel_on = False
        self._audio_on = False
        self._lock = threading.RLock()
        self._btn_offset = None   # host - device clock, min over presses (latency floor)

    def _call(self, label, fn, *args) -> bool:
        if not self.connected or self.dev is None:
            return False
        try:
            with self._lock:
                r = fn(*args)
            if r.is_err():
                log.warning("%s failed: %r", label, r.err_value)
                return False
            return True
        except Exception as ex:  # SerialException, UnwrapError on unplug
            log.error("%s raised %s: device disconnected", label, ex)
            self.connected = False
            return False

    def open(self) -> bool:
        try:
            from freewili import FreeWili

            found = FreeWili.find_first()
            if found.is_err():
                log.info("No FREE-WILi found: %s", found.err_value)
                return False
            self.dev = found.unwrap()
            r = self.dev.open()
            if r.is_err():
                log.warning("open failed: %s", r.err_value)
                return False
            self.dev.set_event_callback(self._on_event)
            self.connected = True
            if config.QUIET:
                self.dev.set_system_sounds(False)
            log.info("Connected: %s", self.dev)
            return True
        except Exception as ex:
            log.warning("FREE-WILi open error: %s", ex)
            self.connected = False
            return False

    def close(self):
        if self.dev is not None:
            try:
                for fn in (self.dev.enable_accel_events, self.dev.enable_button_events):
                    fn(False)
                self.dev.enable_audio_events(False)
                for io in range(7):
                    self.dev.set_board_leds(io, 0, 0, 0)
                self.dev.reset_display()  # back to the FREE-WILi menu on exit
                self.dev.close()
            except Exception:
                pass
        self.connected = False

    def _on_event(self, event_type, frame, data):
        from freewili.types import AccelData, AudioData, ButtonData, EventType

        now = time.perf_counter()
        if event_type == EventType.Accel and isinstance(data, AccelData):
            k = config.COUNTS_PER_G * (data.g / 2.0 if data.g else 1.0)
            self.accel.append((now, float(getattr(frame, "timestamp", 0) or 0), data.x / k, data.y / k, data.z / k))
        elif event_type == EventType.Button and isinstance(data, ButtonData):
            t = self._button_time(now, getattr(frame, "timestamp", 0))
            for c in COLORS:
                v = bool(getattr(data, c))
                if v and not self._buttons.get(c):
                    self._press(c, t)
                self._buttons[c] = v
        elif event_type == EventType.Audio and isinstance(data, AudioData):
            if self._audio_on:
                self.audio.extend(data.data)

    def _button_time(self, host_now: float, dev_raw) -> float:
        """Press time on the host clock from the device timestamp (us on fw v54). Arrival times are
        bursty over USB, which would make tap rhythm look irregular; device stamps are not."""
        if not dev_raw:
            return host_now
        dev = float(dev_raw) / 1e6
        off = host_now - dev
        if self._btn_offset is None or off < self._btn_offset or off - self._btn_offset > 5:
            self._btn_offset = off   # re-anchor if the device clock jumped
        return dev + self._btn_offset

    def pump(self, seconds: float = 0.02):
        end = time.perf_counter() + seconds
        while True:
            if not self.connected:
                time.sleep(seconds)
                return
            try:
                with self._lock:
                    self.dev.process_events()
            except Exception as ex:
                log.error("process_events failed: %s", ex)
                self.connected = False
                return
            if time.perf_counter() >= end:
                return

    def show(self, text):
        ok = self._call("show_text_display", self.dev.show_text_display, text) if self.dev else False
        if self.buttons_on:  # set text before (re)enabling buttons: see hardware/NOTES.md
            self._call("enable_button_events", self.dev.enable_button_events, True, 10)
        return ok

    def led(self, io, rgb):
        r, g, b = rgb
        return self._call("set_board_leds", self.dev.set_board_leds, io, r, g, b) if self.dev else False

    def show_image(self, name):
        # bare filename works, "/images/x.fwi" returns Invalid (hardware/NOTES.md)
        ok = self._call("show_gui_image", self.dev.show_gui_image, f"{name}.fwi") if self.dev else False
        if self.buttons_on:
            self._call("enable_button_events", self.dev.enable_button_events, True, 10)
        return ok

    def upload_image(self, local_path, name):
        ok = self._call("send_file", self.dev.send_file, str(local_path), f"/images/{name}.fwi") if self.dev else False
        if ok:
            self.images.add(name)
        return ok

    def leds(self, rgb):
        r, g, b = rgb
        return all([self._call("set_board_leds", self.dev.set_board_leds, io, r, g, b) for io in range(7)]) if self.dev else False

    def say_number(self, n):
        if config.QUIET:
            return True
        return self._call("play_audio_number_as_speech", self.dev.play_audio_number_as_speech, int(n)) if self.dev else False

    def play(self, name):
        if config.QUIET:
            return name in self.sounds  # pretend it played so nothing falls back to the laptop
        return self._call("play_audio_file", self.dev.play_audio_file, name) if self.dev else False

    def upload(self, local_path, name):
        ok = self._call("send_file", self.dev.send_file, str(local_path), f"/sounds/{name}") if self.dev else False
        if ok:
            self.sounds.add(name)
        return ok

    def stream_accel(self, on):
        self._accel_on = on
        return self._call("enable_accel_events", self.dev.enable_accel_events, on, config.ACCEL_INTERVAL_MS) if self.dev else False

    def stream_buttons(self, on):
        self.buttons_on = on
        return self._call("enable_button_events", self.dev.enable_button_events, on, 10) if self.dev else False

    def stream_audio(self, on):
        if on:
            self.audio = []
        self._audio_on = on
        return self._call("enable_audio_events", self.dev.enable_audio_events, on) if self.dev else False


class SimDevice(BaseDevice):
    """Generates realistic signals for the current synthetic motor state.
    `state` in [0,1] (1 = ON). Buttons are simulated during the tap test."""
    name = "simulated"

    def __init__(self, state: float = 0.8, rate_hz: float = 79.0, seed: int | None = None):
        super().__init__()
        self.state = state
        self.rate = rate_hz
        self.rng = np.random.default_rng(seed)
        self.mode = "rest"     # rest | flip | tremor | taps | voice
        self._accel_on = self._audio_on = False
        self._t_dev = 0.0
        self._frac = 0.0
        self._last = time.perf_counter()
        self._next_tap = None
        self._tap_color = "yellow"
        self.sounds = set()
        self.log: list[str] = []

    def open(self):
        self.connected = True
        return True

    def show(self, text):
        self.log.append(f"screen: {text!r}")
        return True

    def leds(self, rgb):
        self.log.append(f"leds: {rgb}")
        return True

    def led(self, io, rgb):
        return True

    def show_image(self, name):
        self.log.append(f"image: {name}")
        return name in self.images

    def upload_image(self, local_path, name):
        self.images.add(name)
        return True

    def say_number(self, n):
        self.log.append(f"speak: {n}")
        return True

    def play(self, name):
        self.log.append(f"play: {name}")
        return name in self.sounds

    def upload(self, local_path, name):
        self.sounds.add(name)
        return True

    def stream_accel(self, on):
        self._accel_on = on
        return True

    def stream_audio(self, on):
        if on:
            self.audio = []
        self._audio_on = on
        return True

    def _accel_sample(self, t):
        s, rng = self.state, self.rng
        noise = 0.004 * rng.standard_normal(3)
        if self.mode == "flip":
            f = 2.0 + 1.6 * s                # flips per second
            amp = 0.55 + 0.3 * s
            z = amp * math.sin(math.pi * f * t)
            return np.array([0.1, math.sqrt(max(0.0, 1 - z * z)), z]) + noise * 5
        trem_g = (95 - 70 * s) / 1000 * math.sqrt(2)
        f = 5.2
        v = np.array([0.05, 0.02, 1.0]) + noise
        v[0] += trem_g * math.sin(2 * math.pi * f * t)
        v[1] += 0.5 * trem_g * math.sin(2 * math.pi * f * t + 1.0)
        return v

    def pump(self, seconds=0.02):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(0.005)
            now = time.perf_counter()
            dt = now - self._last
            self._last = now
            if self._accel_on:
                self._frac += dt * self.rate
                n = int(self._frac)
                self._frac -= n
                for k in range(n):
                    self._t_dev += 1 / self.rate
                    x, y, z = self._accel_sample(self._t_dev)
                    self.accel.append((now - (n - k - 1) / self.rate, 0.0, x, y, z))
            if self._audio_on and self.mode == "voice":
                n = int(dt * config.MIC_RATE_HZ)
                t = np.arange(n) / config.MIC_RATE_HZ + self._t_dev
                lvl = 3000 + 4000 * self.state
                wob = 1 + (0.4 - 0.3 * self.state) * np.sin(2 * np.pi * 1.7 * t)
                sig = lvl * wob * np.sin(2 * np.pi * 170 * t) - 1200 + 80 * self.rng.standard_normal(n)
                self.audio.extend(sig.astype(int).tolist())
            if self.mode == "taps":
                rate = 2.3 + 1.9 * self.state
                if self._next_tap is None:
                    self._next_tap = now
                while self._next_tap <= now:
                    self._press(self._tap_color, self._next_tap)
                    self._tap_color = "green" if self._tap_color == "yellow" else "yellow"
                    cv = 0.35 - 0.22 * self.state
                    self._next_tap += max(0.05, (1 / rate) * (1 + cv * self.rng.standard_normal()))
            else:
                self._next_tap = None
