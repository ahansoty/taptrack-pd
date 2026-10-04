# TapTrack PD progress

## Done
- Phase 0: venv, requirements, .env created. All API keys blank (features disabled behind env vars).
- Phase 1: hardware verified, see HARDWARE_NOTES.md. hw_test.py fixed (send_file path, device timestamps, tone fallback).

- Phase 2: bridge. `taptrack/` package: device (FREE-WILi + simulated), bridge (guided check, red=dose,
  blue=start/next, gray=cancel, passive tremor), metrics (numpy/scipy) + scoring vs personal baseline,
  storage (TimescaleDB if DATABASE_URL else SQLite), FastAPI + websocket. 33 pytest tests pass.
  Verified silently on the real device; found the accel stream is motion-gated (HARDWARE_NOTES.md).
- QUIET=true in .env (library). Set QUIET=false for the demo.

- Phase 3: synthetic data (`taptrack/synth.py`, `python scripts/seed.py`). 14 days, levodopa 8/12/16/20 with
  +/-8 min jitter and one late dose, onset ~36 min, wear-off from ~3.2 h, noise, slight 14-day decline,
  ~8% missed checks plus one missed afternoon. Mean score by time since dose: 0-30 min 28, 1-3 h ~82,
  3-4 h 44. Auto-seeded on server start if no recent synthetic data.

- Phase 4: dashboard served by FastAPI. `/` clinician (latest score, 14-day tiles, today's curve with
  dose markers, dose-response curve +/-SD, 14-day heatmap by hours since dose, per-test peak vs late,
  live websocket panel, visit report panel, agent actions), `/caregiver` (status in words, last/next dose,
  missed checks, messages). Light + dark, keyboard accessible, tables for every chart, phone width OK.
  Footer: "Decision support for clinicians. Not a diagnostic device."

- Wrist screens: 14 full-screen 320x240 images (`screens/design.py`, theme "clinical" chosen from 3 directions
  in `screens/themes.png`), converted to .fwi and uploaded once (hash manifest, never during a test).
  Home screen follows the latest result / check due / dose logged; tests use one instruction per screen;
  7 board LEDs show the countdown and progress; the exact score is spoken, screens show the word.
  Figma: import `screens/svg/*.svg`, edit, then `python scripts/figma_sync.py` (needs FIGMA_TOKEN, FIGMA_FILE_KEY).
- Dashboard restyled to the same clinical theme (Inter, navy/teal, soft cards; palette validated for CVD).

- Phase 5: spoken instructions (`python scripts/make_audio.py --upload`). Mono 16-bit WAV at FW_WAV_RATE
  (16 kHz), 8.3 names (welcome/flip/tremor/taps/voice/done/dose.wav) + beep/go/end.wav (tone API is broken
  on fw v54). Uploaded to /sounds, re-uploaded automatically when a file changes. ElevenLabs when the key is
  set, Windows SAPI voice otherwise. Played on the wrist during the check; laptop playback fallback.
  play_audio_file returned Ok at 8, 16 and 22.05 kHz; audible check pending (QUIET=true in the library).

## Disabled (missing keys)
- Tiger Data (DATABASE_URL) -> SQLite fallback
- Gemini (GEMINI_API_KEY) -> template report
- ElevenLabs (ELEVENLABS_API_KEY) -> on-device number speech + laptop TTS fallback
- Agentverse (AGENTVERSE_API_KEY) -> mailbox registration via Inspector link

## You need to do
- Tell me which of the t8k/t16k/t22k test tones you heard (sets FW_WAV_RATE).
