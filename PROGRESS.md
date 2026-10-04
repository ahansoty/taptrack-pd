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
  (8 kHz: the device plays at 8 kHz), 8.3 names (welcome/flip/tremor/taps/voice/done/dose.wav) + beep/go/end.wav (tone API is broken
  on fw v54). Uploaded to /sounds, re-uploaded automatically when a file changes. ElevenLabs when the key is
  set, Windows SAPI voice otherwise. Played on the wrist during the check; laptop playback fallback.
  play_audio_file returned Ok at 8, 16 and 22.05 kHz; audible check pending (QUIET=true in the library).

- Phase 6: FinchNode + reports. FinchNode public demo API (no key) loads the patient record
  (default `patient-demo-polypharmacy`, 78 y, 14 active meds) on startup; a levodopa order would set the
  dose times, but no demo patient has one, so the schedule falls back to config and says so. FinchNode is
  read-only (POST returns 404), so every check becomes a FHIR R4 Observation in the local outbox
  ("write-back queue") instead of pretending to write. "Generate visit report" -> neurologist report +
  patient summary: Gemini when GEMINI_API_KEY is set, deterministic template otherwise; a guard strips any
  sentence that reads as medication advice (tested).

- Phase 7: Fetch.ai + Photon. `agent/taptrack_agent.py` runs a Bureau of two uAgents: `taptrack-care`
  (mailbox, Agentverse, AgentChatProtocol 0.3.0 for ASI:One) and `taptrack-clinic` (scheduling desk).
  The care agent decides: red check -> caregiver iMessage; recent missed check -> patient reminder;
  wearing-off pattern -> report + FollowUpRequest to the clinic agent -> offer -> caregiver iMessage.
  Verified locally: Almanac registration OK, wearing-off -> report -> clinic offer -> notify, simulated red
  check -> agent alert within seconds. Photon sidecar `photon/sidecar.mjs` (spectrum-ts 12.10.1, cloud
  iMessage, no Mac) sends and answers caregiver replies through `/api/chat` with per-sender context.
  Server sends the red alert itself if the agent is offline. Dashboard: agent/iMessage status, "Send test
  message", "Simulate wearing-off check". SUBMISSION.md has the ASI:One steps.

- Phase 8: hardening. DEMO_MODE replay on disconnect (tested), `./start.sh [--demo]` starts server + bridge +
  Photon sidecar + agents (installs on first run), 45 pytest tests pass, `scripts/e2e_live.py` verified a live
  check arriving in the browser over the websocket (58 s, all four tests measured) with the real FREE-WILi
  attached. README has setup + the 3-minute demo script.

## Live integrations (keys added 2026-10-04)
- Tiger Data path: Neon Postgres 18 + TimescaleDB 2.24, hypertables checks/doses/passive in schema `taptrack`
  (that database already had another app's tables in `public`, e.g. checks/doses/outbox; we never touch them).
- Gemini `gemini-3.5-flash-lite` writes the visit report (~9 s); the guard removed 1 advice-like sentence on the first run.
- ElevenLabs: voice "Sarah" (premade; free plans can't use library voices via API), prompts uploaded to the wrist.
- Photon: Spectrum connects (project "rehab"); needs CAREGIVER_PHONE / PATIENT_PHONE to send.
- FinchNode sandbox key works; sandbox has no consented user yet, so the public demo record is used and labeled.

## Disabled / pending
- iMessage sends: no phone numbers in .env yet.
- FinchNode sandbox patient: consent pending at the hosted Connect link.
- Agentverse mailbox: one-time Inspector click.

## You need to do
1. Add CAREGIVER_PHONE and PATIENT_PHONE (E.164) to .env and register both under Users in the Photon dashboard;
   restart `./start.sh`. Rotate the keys pasted in chat after the hackathon.
2. Agentverse: open the "Agent inspector" link printed in data/agent.log -> Connect -> Mailbox; fill the Agent Profile.
3. Push a public GitHub repo, record the 3-5 min video, register with the MHacks ASI:One Submission Agent (SUBMISSION.md).
4. Before the demo: set QUIET=false, and confirm you can hear the wrist prompts (t8k/t16k/t22k all played; audibility unchecked).
5. Do one real check on the wrist (physical) to calibrate the score for a healthy wearer.
