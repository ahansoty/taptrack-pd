# Hardware notes (measured 2026-10-03, freewili 0.0.51, firmware v54)

Measured with `hardware/device_test.py`, `hardware/buttons.py` and `hardware/motion_probe.py`.

## What works
| Feature | Result |
|---|---|
| Connect (`FreeWili.find_first`) | OK (COM5 main, COM3 display) |
| `show_text_display` | OK |
| `set_board_leds(io 0..6, r, g, b)` | OK (returns Ok) |
| `play_audio_number_as_speech(42)` | OK |
| `play_audio_tone` | **FAILS** on v54: `Err('')` for every freq/duration/amplitude tried. We use uploaded beep .wav files instead. |
| `send_file(local, "/sounds/x.wav")` + `play_audio_file("x.wav")` | OK at 8, 16, 22.05 kHz mono 16-bit. Upload ~1.6 s for 16 KB, ~2.6 s for 44 KB (~25 KB/s incl. overhead). |
| Buttons | All five (gray, yellow, green, blue, red) register as clean press/release events. |
| Mic (`enable_audio_events`) | OK. 8 samples per event, ~1000 events/s, so **~8 kHz** effective. Big DC offset (~-1200) and clips at +/-32700; remove mean before RMS. |

## Accelerometer
Requested interval vs real rate (device flat, 3 s windows):

| interval_ms | real rate |
|---|---|
| 100 | erratic (backlog) |
| 50 | ~7.5 Hz |
| 20 | ~17.6 Hz |
| 10 | ~40 Hz |
| 5 | **~79 Hz** |

- **The accel stream is motion-gated** (re-measured with `hardware/motion_probe.py`): lying still on a
  table the device sends only ~1 event/s at any interval; held in the hand it sends ~84/s, waving ~117/s.
  The 79 Hz above was measured while it was being handled. Worn on a wrist it streams continuously.
  Consequences: (1) we treat a stream < 20 Hz during a test as "not worn" and flag it; (2) passive tremor
  is only sampled when the stream is >= 20 Hz and the wrist is still; (3) linear resampling across gaps
  is correct because a gap means "value unchanged".
- Real rate (when handled) is ~35-40% of the nominal rate. **We use interval 5 ms (~79 Hz)** for all accel tests, so tremor
  dominant frequency (3-12 Hz FFT) is enabled (rate >= 40 Hz). If a session measures < 40 Hz, the code
  automatically falls back to strength only.
- Delivery over USB is bursty (0 to ~100 events in 1.5 s windows), so we timestamp samples with the
  **device frame timestamp**, which is in **microseconds** (the library comments say ns; the data says us),
  and resample to a uniform grid before filtering.
- At rest on the 2g range: |a| ~ 16,700 counts, so **~16,384 counts/g** confirmed. Noise sd ~0.07 g per axis.

## Gotchas found by reading the library source
- `send_file(path, "test.wav")` uploads to the **root**, not `/sounds`. Use `"/sounds/test.wav"` (or `None` to auto-map).
- Every call returns a `result.Result`; Err messages from firmware can be empty strings.
- Set screen text **before** enabling button events (the bridge re-enables buttons after every screen update).
- `set_system_sounds(False)` works (returns the menu prompt `Enter Letter:` as Ok). There is no volume API;
  `QUIET=true` mutes all wrist + laptop audio. Pulling the USB raises `SerialException` from the reader
  thread; the bridge catches this and switches to DEMO_MODE replay.

## Design decisions based on this
- Accel at 5 ms requested interval, device timestamps, resampled to 50 Hz uniform for metrics.
- Tremor frequency enabled (measured rate >= 40 Hz), with automatic fallback.
- Beeps = uploaded `beep.wav` files (tone API broken).
- Voice test uses ~8 kHz mic samples, DC removed, 100 ms RMS windows.
- Instruction audio uploaded at 16 kHz by default (`FW_WAV_RATE`), 8 kHz if uploads are too slow.

## Display (verified 2026-10-03)
- Resolution **320 x 240**, landscape. A 320x240 calibration image filled the screen exactly with all four edges visible.
- `show_gui_image("name.fwi")` works with the **bare filename**; `"/images/name.fwi"` returns `Err('Invalid')`.
- Upload with `send_file(local, "/images/name.fwi")`: 153,624 bytes (header + 320x240x2) in ~5.5 s. All 14 screens: 76 s.
- `freewili.image.convert` maps any pixel that truncates to RGB565 0 to transparent; `screens/design.py` lifts
  such pixels to (9,5,9) and the palettes avoid pure black.
- Buttons left to right under the screen: gray, yellow, green, blue, red (on-screen legend matches).
- Some `show_text_display` strings return `Invalid` (seen with underscores); screens are images now, text is
  only a fallback.

## Audio playback rate (verified by ear, 2026-10-04)
- `play_audio_file` plays at **8 kHz** regardless of the WAV header. 16/22/24/44 kHz files play slowed and
  low-pitched ("demonic"). All prompts and beeps are generated at 8 kHz (`FW_WAV_RATE=8000`).
- No volume API: files are scaled to `VOLUME` (0.55). The built-in number speech can't be scaled.
