# TapTrack PD: project context for Claude Code

## What we are building
A wrist-worn Parkinson's "wearing-off" tracker for MHacks 2026 (submission deadline Sunday Oct 4, 12 PM on Devpost; judging 12:30 to 2:30 PM, 3-minute pitch).

Most Parkinson's patients take levodopa, and doses wear off before the next one. Neurologists adjust timing from patient memory at visits months apart. TapTrack PD measures motor function several times a day on the wrist, tags every reading with time since last dose, and shows the neurologist a dose-response curve.

Pitch line: "Parkinson's changes hour by hour, but neurologists see it a few times a year. TapTrack PD shows them the hours they're missing."

## Hardware (only this, nothing else available)
- ONE original FREE-WILi (no touchscreen), worn on a watch strap.
- Connected to the laptop by a long USB cable. NO wireless. The product pitch is "wear all day, dock at night to sync, like a Holter monitor."
- No extra sensors, wires, or foil.

## FREE-WILi Python library (`pip install freewili`), verified API
```python
from freewili import FreeWili
from freewili.types import EventType, AccelData, ButtonData, AudioData

with FreeWili.find_first().expect("No FREE-WILi found") as dev:
    dev.set_event_callback(cb)            # cb(event_type: EventType, frame, data)
    dev.enable_accel_events(True, 20)     # interval_ms; default 100. MEASURE real rate.
    dev.enable_button_events(True, 10)
    dev.enable_audio_events(True)         # data: AudioData.data -> list[int] raw samples
    while True:
        dev.process_events()
```
- AccelData fields: g (range), x, y, z, temp_c, temp_f. Raw units; at 2g range, ~16384 counts per g (verify from data at rest).
- ButtonData fields: gray, yellow, green, blue, red (bools).
- Output: set_board_leds(io, r, g, b), show_text_display(text), play_audio_tone(freq_hz, duration_sec, amplitude), play_audio_number_as_speech(int).
- Audio files: send_file(local_path, target_name) uploads .wav into /sounds; play_audio_file(name) plays it. 8.3 filename limit (e.g. flip.wav).
- Every call returns a Result (Ok/Err from the `result` package). Check it, never assume success.
- Always read the installed library source if unsure; do not invent methods.

## Button mapping
- red: "took meds" (dose log)
- yellow / green: alternating tap test
- blue: start next test
- gray: cancel / back

## Daily check (about 1 minute)
1. Hand flipping, 10 s, rapid palm up/down (accel): flips/sec, amplitude, decrement (first third vs last third).
2. Tremor, hold still 20 s (accel): RMS of high-passed magnitude; dominant frequency via FFT in 3 to 12 Hz ONLY if measured sample rate >= 40 Hz, else report strength only.
3. Alternating taps, 10 s (yellow/green): tap rate, inter-tap interval coefficient of variation, decrement.
4. Voice, "ahhh" 5 s (audio events): RMS loudness and loudness stability.
Plus passive tremor sampling between tests.
Composite score 0 to 100 vs the user's own baseline. LEDs green/yellow/red; speak the score with play_audio_number_as_speech.

## Sponsors and their real jobs
- FREE-WILi: the wearable (accel, mic, buttons, LEDs, speech, speaker).
- Tiger Data: Postgres/TimescaleDB, hypertable for readings and test results. Fallback SQLite if DATABASE_URL unset.
- FinchNode: patient record + medication schedule from their synthetic records; write results back. Do not guess endpoints, ask the user for docs.
- Gemini: neurologist report + plain-language patient summary. MUST describe patterns only, never recommend dose changes.
- ElevenLabs: pre-generate spoken test instructions, convert to .wav, upload to FREE-WILi, play on the wrist. Laptop playback as fallback.
- Fetch.ai: separate phase. uAgent registered on Agentverse, discoverable via ASI:One. Sends report, books follow-up, reminds missed tests.
- Figma (dashboard design), Notability (screenshots), .tech domain: non-code.

## Rules
- Every integration is behind an env var and must fail gracefully (app still runs with zero keys).
- Build in phases. After each phase, stop, say exactly how to test it, and wait.
- Hardware first: nothing else matters if the device stream is not verified.
- Keep a DEMO_MODE that can replay synthetic data if the hardware disconnects during judging.
- This is decision support for clinicians, not a diagnostic device. Say so in the UI footer.
