# TapTrack PD progress

## Done
- Phase 0: venv, requirements, .env created. All API keys blank (features disabled behind env vars).
- Phase 1: hardware verified, see HARDWARE_NOTES.md. hw_test.py fixed (send_file path, device timestamps, tone fallback).

- Phase 2: bridge. `taptrack/` package: device (FREE-WILi + simulated), bridge (guided check, red=dose,
  blue=start/next, gray=cancel, passive tremor), metrics (numpy/scipy) + scoring vs personal baseline,
  storage (TimescaleDB if DATABASE_URL else SQLite), FastAPI + websocket. 33 pytest tests pass.
  Verified silently on the real device; found the accel stream is motion-gated (HARDWARE_NOTES.md).
- QUIET=true in .env (library). Set QUIET=false for the demo.

## Disabled (missing keys)
- Tiger Data (DATABASE_URL) -> SQLite fallback
- Gemini (GEMINI_API_KEY) -> template report
- ElevenLabs (ELEVENLABS_API_KEY) -> on-device number speech + laptop TTS fallback
- Agentverse (AGENTVERSE_API_KEY) -> mailbox registration via Inspector link

## You need to do
- Tell me which of the t8k/t16k/t22k test tones you heard (sets FW_WAV_RATE).
