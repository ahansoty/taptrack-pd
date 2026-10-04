"""Device bridge: owns the device, runs the guided daily check, logs doses on red,
samples passive tremor while idle, stores everything, and publishes live events.

Buttons: red = took meds, blue = start / next test, gray = cancel, yellow+green = taps.
If the FREE-WILi disconnects and DEMO_MODE is on, a simulated device replays checks
driven by the synthetic wearing-off model so the dashboard keeps updating.
"""
from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time

from . import analysis, audio, config, metrics, scoring, synth
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


SCREEN_DIR = config.ROOT / "screens" / "fwi"
HOME_BY_LEVEL = {"good": "home_g", "fair": "home_y", "low": "home_r"}
RESULT_BY_LEVEL = {"good": "res_g", "fair": "res_y", "low": "res_r"}
HOME_TEXT = {  # text fallback when screens aren't uploaded
    "home_n": "TapTrack PD\nblue = check\nred = took meds", "home_g": "TapTrack PD\nLast check: GOOD",
    "home_y": "TapTrack PD\nLast check:\nLOWER THAN USUAL", "home_r": "TapTrack PD\nLast check:\nMUCH LOWER",
    "home_due": "TapTrack PD\nCHECK DUE\npress blue", "home_med": "Dose logged",
}
RESULT_HOLD_S = float(config.env("RESULT_HOLD_S", "60"))  # result screen, then back to main
DOSE_CONFIRM_S = 3.0
LED_PROGRESS = (40, 40, 60)
LED_COUNT = (0, 0, 90)


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
        self._home_override = None   # (screen, until_ts)
        self._baseline = None        # cached personal baseline (loaded once)
        self._last_home = 0.0

    # ------------------------------------------------------------ public API (any thread)
    def request_check(self, simulate: bool = False, state: float | None = None):
        self.commands.put(("check", (simulate, state)))

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
        dev.leds((0, 0, 0))
        self._sync_sounds()
        self._sync_screens()
        self._home(force=True)

    def _sync_screens(self):
        """Upload wrist screens once (screens/fwi, built after design approval). Tracked by content
        hash so unchanged screens are never re-sent; never called during a test (~6 s per screen)."""
        dev = self.device
        if isinstance(dev, SimDevice):
            dev.images.update(p.stem for p in SCREEN_DIR.glob("*.fwi"))
            return
        if not isinstance(dev, FreeWiliDevice) or not SCREEN_DIR.exists():
            return
        known = dict(self.store.get_setting("fw_images", {}) or {})
        for path in sorted(SCREEN_DIR.glob("*.fwi")):
            digest = hashlib.sha1(path.read_bytes()).hexdigest()[:12]
            if known.get(path.stem) == digest:
                dev.images.add(path.stem)
                continue
            dev.show("Setting up\nscreens " + path.stem.replace("_", " "))  # "_" can make text Invalid
            if dev.upload_image(path, path.stem):
                known[path.stem] = digest
                self.store.set_setting("fw_images", known)
        log.info("device screens: %s", sorted(dev.images))

    # ------------------------------------------------------------ home screen
    def _desired_home(self) -> str:
        """The main screen whenever idle. Only transient screens (a result for up to 60 s, a short
        dose confirmation) override it, and any button press dismisses them."""
        if self._home_override and time.time() < self._home_override[1]:
            return self._home_override[0]
        if self._home_override:  # override just expired: back to main, LEDs off
            self._home_override = None
            if self.device:
                self.device.leds((0, 0, 0))
        return "home_n"

    def _dismiss_overlay(self) -> bool:
        """A press while a result/confirmation is showing only returns to the main screen."""
        if self._home_override and time.time() < self._home_override[1]:
            self._home_override = None
            if self.device:
                self.device.leds((0, 0, 0))
            self._home(force=True)
            return True
        return False

    def _home(self, force=False):
        dev = self.device
        if not dev or self.state == "check":
            return
        name = self._desired_home()
        if force or dev.current_screen != name:
            dev.screen(name, HOME_TEXT.get(name, "TapTrack PD"))

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
        sim.open()
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
            if self._dismiss_overlay():
                continue
            if c == "red":
                self._log_dose("button")
            elif c == "blue":
                self.run_check()
        self._maybe_passive()
        if time.time() - self._last_home > 2:
            self._last_home = time.time()
            self._home()
        if self.demo and time.time() - self._last_demo > self.demo_interval_s:
            self._last_demo = time.time()
            self.run_check(simulate=True)

    def _handle_commands(self):
        while not self.commands.empty():
            cmd, arg = self.commands.get_nowait()
            if cmd == "dose":
                self._log_dose(arg)
            elif cmd == "check":
                sim, forced = arg if isinstance(arg, tuple) else (arg, None)
                self.run_check(simulate=sim, state=forced)

    # ------------------------------------------------------------ actions
    def _log_dose(self, source):
        ts = self.store.add_dose(source=source)
        log.info("dose logged (%s)", source)
        dev = self.device
        if dev:
            if not dev.play("dose.wav"):
                dev.play("go.wav") or audio.play_local("dose.wav", audio.PROMPTS["dose.wav"])
            if self.state != "check":
                self._home_override = ("home_med", time.time() + DOSE_CONFIRM_S)
                self._home(force=True)
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

    def _wait(self, seconds, progress=False):
        """Pump the device; red logs a dose, gray cancels. progress=True fills the 7 LEDs."""
        start = time.time()
        end = start + seconds
        lit = None
        while time.time() < end:
            self.device.pump(0.03)
            self._drain(allow_blue=False)
            if progress and seconds > 0:
                lit = self.device.progress((time.time() - start) / seconds, LED_PROGRESS, lit)

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
            start = time.time()
            end = start + seconds
            lit = None
            while time.time() < end:
                dev.pump(0.02)
                lit = dev.progress((time.time() - start) / seconds, LED_PROGRESS, lit)
                while not self.presses.empty():
                    c = self.presses.get_nowait()
                    if c == "gray":
                        raise Cancelled()
                    if c == "red":
                        self._log_dose("button")
            taps = [(t - t_start, c) for t, c in list(dev.presses) if t >= t_start - 0.3 and c in ("yellow", "green")]
            self._dump_raw(name, presses=[(t, c) for t, c in list(dev.presses) if t >= t_start - 0.3])
            result = metrics.alternating_taps(taps, seconds)
        else:
            self._wait(seconds, progress=True)
            if name == "voice":
                dev.stream_audio(False)
                result = metrics.voice(dev.audio, config.MIC_RATE_HZ)
            else:
                rows = [r for r in list(dev.accel) if r[0] >= t_start]
                self._dump_raw(name, rows=rows)
                t, xyz = accel_arrays(rows)
                result = metrics.hand_flip(t, xyz) if name == "flip" else metrics.tremor(t, xyz)
                if len(t) > 1 and metrics.measured_rate(t) < NOT_WORN_HZ:
                    result["not_worn"] = True
                    self.publish({"type": "alert", "text": "Wrist barely moved: is the device on the wrist?"})
        if isinstance(dev, SimDevice):
            dev.mode = "rest"
        return result

    def _dump_raw(self, step, rows=None, presses=None):
        """Keep the raw samples of the latest real check for debugging (data/raw/<step>.json)."""
        if isinstance(self.device, SimDevice):
            return
        try:
            import json

            d = config.DATA_DIR / "raw"
            d.mkdir(exist_ok=True)
            (d / f"{step}.json").write_text(json.dumps({"rows": rows or [], "presses": presses or []}))
        except Exception:
            log.exception("raw dump failed")

    def run_check(self, simulate: bool = False, state: float | None = None):
        if self.state == "check":
            return None
        prev_state, prev_dev = self.state, self.device
        if simulate and not isinstance(self.device, SimDevice):
            # dashboard-triggered simulated check without touching hardware
            sim = SimDevice(state=self._synthetic_state_now())
            sim.open()
            sim.on_press = self.presses.put
            sim.stream_accel(True)  # a dashboard-triggered sim check needs its own accel stream
            self.device = sim
        dev = self.device
        if isinstance(dev, SimDevice):
            dev.state = self._synthetic_state_now() if state is None else state
        self.state = "check"
        results, started = {}, time.time()
        source = "demo" if isinstance(dev, SimDevice) else "device"
        self.publish({"type": "check_started", "ts": started, "source": source})
        try:
            dev.leds((0, 0, 0))
            for name, seconds, text in STEPS:
                self.step = name
                # one instruction per screen: the test screen, then "get ready" while waiting for blue
                dev.screen(name, text + "\nblue = start")
                self.publish({"type": "step", "step": name, "phase": "instruct", "seconds": seconds})
                self._say(f"{name}.wav")
                if not (self.auto_advance or isinstance(dev, SimDevice)):
                    self._wait(2.5)
                    dev.screen("ready", "Get ready\npress blue")
                self._wait_for_go()
                dev.screen(name, text)
                # countdown on the LEDs: all 7 blue, emptying in thirds with a beep each
                lit = dev.progress(1.0, LED_COUNT)
                for n in (3, 2, 1):
                    self._beep("beep.wav")
                    self._wait(0.7 * min(1.0, self.duration_scale * 10))
                    lit = dev.progress((n - 1) / 3, LED_COUNT, lit)
                self._beep("go.wav")
                self.publish({"type": "step", "step": name, "phase": "record", "seconds": seconds})
                r = self._record(name, seconds * self.duration_scale)
                self._beep("end.wav")
                dev.progress(0, LED_PROGRESS, 7)
                results[name] = r
                self.publish({"type": "step", "step": name, "phase": "done", "result": r})
            complete = True
            dev.screen("calc", "Calculating\nyour score")
        except Cancelled:
            complete = False
            dev.leds((0, 0, 0))
            self.publish({"type": "check_cancelled"})
        finally:
            self.step = None
        try:
            row = self._finish(results, complete, source)
        except Exception:
            log.exception("finishing the check failed")
            row = None
            self._home_override = None
        if dev is not prev_dev:
            self.device = prev_dev
        self.state = prev_state if prev_state != "check" else "idle"
        if dev is not prev_dev:
            self._home_override = None  # a simulated check never takes over the real wrist's screen
        self._home(force=dev is not prev_dev or row is None)
        self.publish({"type": "device", **self.status()})
        return row

    def _finish(self, results, complete, source):
        if not results:
            return None
        t_done = time.time()
        if self._baseline is None:
            try:
                b = self.store.get_setting("baseline")
                self._baseline = {k: tuple(v) for k, v in b.items()} if b else {}
            except Exception:
                log.exception("baseline unavailable; using defaults")
                self._baseline = {}
        s = scoring.score(results, self._baseline or None)   # pure math, well under a second
        dev = self.device
        dev.leds(scoring.LED_RGB[s["level"]])
        if s["score"] is not None:
            label = {"good": "GOOD", "fair": "LOWER THAN USUAL", "low": "MUCH LOWER"}[s["level"]]
            # the screen shows the word; the exact score is spoken
            dev.screen(RESULT_BY_LEVEL[s["level"]], f"Check done\n{label}")
            if not (("done.wav" in dev.sounds) and dev.play("done.wav")) and not isinstance(dev, SimDevice):
                audio.play_local("done.wav", audio.PROMPTS["done.wav"])
            self._wait(2.2 if not isinstance(dev, SimDevice) else 0.1)
            if not dev.say_number(s["score"]) and not isinstance(dev, SimDevice):
                audio.play_local(text=str(s["score"]))
            self._home_override = (RESULT_BY_LEVEL[s["level"]], time.time() + RESULT_HOLD_S)
        # save after the patient already sees the result; a slow or sleeping database can't block the wrist
        try:
            row = self.store.add_check(t_done, s["score"], s["level"], s["tests"], s["metrics"], results,
                                       source=source, complete=complete)
        except Exception:
            log.exception("saving the check failed; result shown on the wrist anyway")
            row = {"ts": t_done, "score": s["score"], "level": s["level"], "tests": s["tests"], "metrics": s["metrics"],
                   "results": results, "source": source, "complete": int(complete), "minutes_since_dose": None,
                   "id": None, "save_error": True}
            self.publish({"type": "alert", "text": "Check result could not be saved (database unreachable)"})
        self.publish({"type": "check_result", **row})
        for fn in self.listeners:
            try:
                fn(row)
            except Exception:
                log.exception("check listener failed")
        return row
