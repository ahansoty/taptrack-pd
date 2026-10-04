"""Device bridge: owns the device, runs the guided daily check, logs doses on red,
samples passive tremor while idle, stores everything, and publishes live events.

Buttons: red = took meds, blue = start / next test, gray = cancel, yellow+green = taps.
If the FREE-WILi disconnects and DEMO_MODE is on, a simulated device replays checks
driven by the synthetic wearing-off model so the dashboard keeps updating.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from . import audio, config, metrics, scoring, synth
from .device import BaseDevice, FreeWiliDevice, SimDevice, accel_arrays
from .storage import Storage

log = logging.getLogger("taptrack.bridge")

STEPS = [
    # name, seconds, screen text
    ("flip", 10, "HAND FLIPS\npalm up/down\nfast 10 s"),
    ("tremor", 20, "TREMOR\nhold still\n20 s"),
    ("taps", 10, "TAPS\nyellow/green\nfast 10 s"),
    ("voice", 5, "VOICE\nsay ahhh\n5 s"),
]


NOT_WORN_HZ = 20.0  # see HARDWARE_NOTES.md: accel events are motion-gated


class Cancelled(Exception):
    pass


class Bridge(threading.Thread):
    def __init__(self, store: Storage, publish=None, device: BaseDevice | None = None,
                 duration_scale: float = 1.0, auto_advance: bool | None = None,
                 demo_interval_s: float | None = None):
        super().__init__(daemon=True, name="taptrack-bridge")
        self.store = store
        self.publish = publish or (lambda ev: None)
        self.device = device
        self.fixed_device = device is not None
        self.duration_scale = duration_scale
        self.auto_advance = config.CHECK_AUTO_ADVANCE if auto_advance is None else auto_advance
        self.demo_interval_s = demo_interval_s or float(config.env("DEMO_INTERVAL_S", "120"))
        self.presses: queue.Queue[str] = queue.Queue()
        self.commands: queue.Queue[tuple] = queue.Queue()
        self.stop_flag = threading.Event()
        self.state = "starting"   # idle | check | disconnected | demo
        self.step = None
        self.listeners = []       # callables(check_row) after each stored check
        self._last_passive = time.time()
        self._last_demo = 0.0
        self._last_reconnect = 0.0
        self.demo = False

    # ------------------------------------------------------------ public API (any thread)
    def request_check(self, simulate: bool = False):
        self.commands.put(("check", simulate))

    def request_dose(self, source="dashboard"):
        self.commands.put(("dose", source))

    def status(self) -> dict:
        d = self.device
        return {"state": self.state, "step": self.step, "device": d.name if d else None,
                "connected": bool(d and d.connected), "demo": self.demo}

    def stop(self):
        self.stop_flag.set()

    # ------------------------------------------------------------ device management
    def _attach(self, dev: BaseDevice):
        self.device = dev
        dev.on_press = self.presses.put
        dev.stream_buttons(True)
        dev.stream_accel(True)
        dev.show("TapTrack PD\nblue = check\nred = took meds")
        dev.leds(scoring.LED_RGB["none"])
        self._sync_sounds()

    def _sync_sounds(self):
        """Upload beeps (tone API is broken on fw v54) and any ElevenLabs prompts not yet on the device."""
        dev = self.device
        if not isinstance(dev, FreeWiliDevice):
            return
        known = set(self.store.get_setting("fw_sounds", []) or [])
        files = audio.ensure_beeps()
        for name in audio.PROMPTS:
            p = audio.local_wav(name)
            if p:
                files[name] = p
        for name, path in files.items():
            stamp = f"{name}:{path.stat().st_size}"
            if stamp in known:
                dev.sounds.add(name)
                continue
            if dev.upload(path, name):
                known.add(stamp)
        self.store.set_setting("fw_sounds", sorted(known))
        log.info("device sounds: %s", sorted(dev.sounds))

    def _connect_real(self) -> bool:
        if not config.USE_DEVICE:
            return False
        dev = FreeWiliDevice()
        if dev.open():
            self._attach(dev)
            self.demo = False
            self.state = "idle"
            self.publish({"type": "device", **self.status()})
            return True
        return False

    def _enter_demo(self):
        sim = SimDevice(state=self._synthetic_state_now())
        self._attach(sim)
        self.demo = True
        self.state = "demo"
        self._last_demo = time.time() - self.demo_interval_s + 15  # first replay soon
        self.publish({"type": "device", **self.status()})

    def _synthetic_state_now(self) -> float:
        now = time.time()
        doses = [d["ts"] for d in self.store.doses(now - 2 * 86400, now + 1)]
        return synth.state_at(now, doses, 1.0) if doses else 0.7

    # ------------------------------------------------------------ main loop
    def run(self):
        if self.fixed_device:
            self.device.open()
            self._attach(self.device)
            self.state = "idle"
        elif not self._connect_real():
            if config.DEMO_MODE:
                log.info("No device: DEMO_MODE replay")
                self._enter_demo()
            else:
                self.state = "disconnected"
                self.publish({"type": "device", **self.status()})
        while not self.stop_flag.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("bridge tick failed")
                time.sleep(0.5)
        if self.device:
            self.device.close()

    def _tick(self):
        dev = self.device
        # lost the real device?
        if isinstance(dev, FreeWiliDevice) and not dev.connected:
            log.warning("FREE-WILi disconnected")
            self.publish({"type": "alert", "text": "Wrist device disconnected" +
                          (", switching to demo replay" if config.DEMO_MODE else "")})
            if config.DEMO_MODE:
                self._enter_demo()
            else:
                self.device = None
                self.state = "disconnected"
                self.publish({"type": "device", **self.status()})
            return
        # try to (re)connect real hardware every 5 s when not on it
        if not self.fixed_device and not isinstance(dev, FreeWiliDevice) and time.time() - self._last_reconnect > 5:
            self._last_reconnect = time.time()
            if self._connect_real():
                self.publish({"type": "alert", "text": "Wrist device connected"})
                return
        if dev is None:
            self._handle_commands()
            time.sleep(0.2)
            return
        dev.pump(0.05)
        self._handle_commands()
        while not self.presses.empty():
            c = self.presses.get_nowait()
            if c == "red":
                self._log_dose("button")
            elif c == "blue":
                self.run_check()
        self._maybe_passive()
        if self.demo and time.time() - self._last_demo > self.demo_interval_s:
            self._last_demo = time.time()
            self.run_check(simulate=True)

    def _handle_commands(self):
        while not self.commands.empty():
            cmd, arg = self.commands.get_nowait()
            if cmd == "dose":
                self._log_dose(arg)
            elif cmd == "check":
                self.run_check(simulate=arg)

    # ------------------------------------------------------------ actions
    def _log_dose(self, source):
        ts = self.store.add_dose(source=source)
        log.info("dose logged (%s)", source)
        dev = self.device
        if dev:
            dev.leds((0, 0, 90))
            if not dev.play("dose.wav"):
                dev.play("go.wav") or audio.play_local("dose.wav", audio.PROMPTS["dose.wav"])
            dev.show("Dose logged\n" + time.strftime("%H:%M"))
        self.publish({"type": "dose", "ts": ts, "source": source})

    def _maybe_passive(self):
        if time.time() - self._last_passive < config.PASSIVE_PERIOD_S or self.state == "check":
            return
        self._last_passive = time.time()
        t, xyz = self.device.accel_window(20)
        # motion-gated stream: < 20 Hz means the device is lying still, i.e. not worn
        if len(t) < 40 or metrics.measured_rate(t) < NOT_WORN_HZ or not metrics.is_still(xyz):
            return
        r = metrics.tremor(t, xyz)
        if r.get("valid"):
            row = self.store.add_passive(time.time(), r["rms_vec_mg"], r["dominant_hz"],
                                         source="demo" if self.demo else "device")
            self.publish({"type": "passive", **row})

    # ------------------------------------------------------------ guided check
    def _say(self, name):
        """Play an instruction on the wrist; fall back to the laptop."""
        dev = self.device
        if name in dev.sounds and dev.play(name):
            return True
        if not isinstance(dev, SimDevice):
            audio.play_local(name, audio.PROMPTS.get(name))
        return False

    def _beep(self, name="beep.wav"):
        dev = self.device
        if not (name in dev.sounds and dev.play(name)) and not isinstance(dev, SimDevice):
            audio.play_local(name)

    def _wait(self, seconds):
        """Pump the device; red logs a dose, gray cancels."""
        end = time.time() + seconds
        while time.time() < end:
            self.device.pump(0.03)
            self._drain(allow_blue=False)

    def _drain(self, allow_blue):
        got_blue = False
        while not self.presses.empty():
            c = self.presses.get_nowait()
            if c == "gray":
                raise Cancelled()
            if c == "red":
                self._log_dose("button")
            if c == "blue" and allow_blue:
                got_blue = True
        return got_blue

    def _wait_for_go(self, timeout=90):
        if self.auto_advance or isinstance(self.device, SimDevice):
            self._wait(1.0 if isinstance(self.device, SimDevice) else 7.0)
            return
        end = time.time() + timeout
        while time.time() < end:
            self.device.pump(0.03)
            if self._drain(allow_blue=True):
                return
        raise Cancelled()

    def _record(self, name, seconds):
        dev = self.device
        if isinstance(dev, SimDevice):
            dev.mode = name
        t_start = time.perf_counter()
        if name == "voice":
            dev.stream_audio(True)
        # taps: drain presses ourselves so yellow/green are captured, not acted on
        if name == "taps":
            end = time.time() + seconds
            while time.time() < end:
                dev.pump(0.02)
                while not self.presses.empty():
                    c = self.presses.get_nowait()
                    if c == "gray":
                        raise Cancelled()
                    if c == "red":
                        self._log_dose("button")
            taps = [(t - t_start, c) for t, c in list(dev.presses) if t >= t_start and c in ("yellow", "green")]
            result = metrics.alternating_taps(taps, seconds)
        else:
            self._wait(seconds)
            if name == "voice":
                dev.stream_audio(False)
                result = metrics.voice(dev.audio, config.MIC_RATE_HZ)
            else:
                rows = [r for r in list(dev.accel) if r[0] >= t_start]
                t, xyz = accel_arrays(rows)
                result = metrics.hand_flip(t, xyz) if name == "flip" else metrics.tremor(t, xyz)
                if len(t) > 1 and metrics.measured_rate(t) < NOT_WORN_HZ:
                    result["not_worn"] = True
                    self.publish({"type": "alert", "text": "Wrist barely moved: is the device on the wrist?"})
        if isinstance(dev, SimDevice):
            dev.mode = "rest"
        return result

    def run_check(self, simulate: bool = False):
        if self.state == "check":
            return None
        prev_state, prev_dev = self.state, self.device
        if simulate and not isinstance(self.device, SimDevice):
            # dashboard-triggered simulated check without touching hardware
            sim = SimDevice(state=self._synthetic_state_now())
            sim.open()
            sim.on_press = self.presses.put
            self.device = sim
        dev = self.device
        if isinstance(dev, SimDevice):
            dev.state = self._synthetic_state_now()
        self.state = "check"
        results, started = {}, time.time()
        source = "demo" if isinstance(dev, SimDevice) else "device"
        self.publish({"type": "check_started", "ts": started, "source": source})
        try:
            dev.leds((0, 0, 60))
            for name, seconds, text in STEPS:
                self.step = name
                dev.show(text + "\nblue = start")
                self.publish({"type": "step", "step": name, "phase": "instruct", "seconds": seconds})
                self._say(f"{name}.wav")
                self._wait_for_go()
                for n in (3, 2, 1):
                    dev.show(f"{text.splitlines()[0]}\n{n}")
                    self._beep("beep.wav")
                    self._wait(0.7 * min(1.0, self.duration_scale * 10))
                dev.show(text.splitlines()[0] + "\nGO")
                self._beep("go.wav")
                self.publish({"type": "step", "step": name, "phase": "record", "seconds": seconds})
                r = self._record(name, seconds * self.duration_scale)
                self._beep("end.wav")
                results[name] = r
                self.publish({"type": "step", "step": name, "phase": "done", "result": r})
            complete = True
        except Cancelled:
            complete = False
            dev.show("Check cancelled")
            self.publish({"type": "check_cancelled"})
        finally:
            self.step = None
        row = self._finish(results, complete, source)
        if dev is not prev_dev:
            self.device = prev_dev
        self.state = prev_state if prev_state != "check" else "idle"
        return row

    def _finish(self, results, complete, source):
        if not results:
            return None
        base = self.store.get_setting("baseline")
        base = {k: tuple(v) for k, v in base.items()} if base else None
        s = scoring.score(results, base)
        row = self.store.add_check(time.time(), s["score"], s["level"], s["tests"], s["metrics"], results,
                                   source=source, complete=complete)
        dev = self.device
        dev.leds(scoring.LED_RGB[s["level"]])
        if s["score"] is not None:
            label = {"good": "GOOD", "fair": "FAIR", "low": "LOW"}[s["level"]]
            dev.show(f"Score {s['score']}\n{label}")
            if not (("done.wav" in dev.sounds) and dev.play("done.wav")) and not isinstance(dev, SimDevice):
                audio.play_local("done.wav", audio.PROMPTS["done.wav"])
            self._wait(2.2 if not isinstance(dev, SimDevice) else 0.1)
            if not dev.say_number(s["score"]) and not isinstance(dev, SimDevice):
                audio.play_local(text=str(s["score"]))
        self.publish({"type": "check_result", **row})
        for fn in self.listeners:
            try:
                fn(row)
            except Exception:
                log.exception("check listener failed")
        return row
