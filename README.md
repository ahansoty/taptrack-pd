# TapTrack PD

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**Parkinson's changes hour by hour, but neurologists see it a few times a year. TapTrack PD shows them the hours they're missing.**

A FREE-WILi on a watch strap runs a one-minute motor check several times a day (hand flips, tremor, alternating
taps, voice), tags every result with the time since the last levodopa dose, and turns the data into a
dose-response picture for the neurologist. Wear it all day, dock it at night to sync, like a Holter monitor.

_Decision support for clinicians. Not a diagnostic device._

## Quick start
```bash
./start.sh --demo        # first run installs everything; then open http://127.0.0.1:8000
```
That starts the FastAPI server and wrist bridge, the Photon iMessage sidecar, and the Fetch.ai agents. With
`--demo`, a simulated wrist replays checks if the FREE-WILi is missing or gets unplugged. Ctrl+C stops everything.

Requirements: Python 3.11+, Node 20+ (for iMessage), ffmpeg (only to regenerate voice prompts), a FREE-WILi on USB.

Manual setup, if you prefer:
```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # .venv/bin on macOS/Linux
.venv/Scripts/pip install -U "typing_extensions>=4.13"                   # google-genai needs it
cp .env.example .env                                                      # keys are optional
python hw_test.py                                                         # verify the device
python -m taptrack.server
```

### One-time device setup
```bash
python screens/design.py --fwi && python scripts/upload_screens.py   # 14 full-screen images (~80 s)
python scripts/make_audio.py --upload                                # spoken instructions (ElevenLabs or Windows voice)
```
Uploads are hashed, so later starts never re-send unchanged files, and nothing uploads during a test.

### Keys (all optional; every feature degrades gracefully)
| Env var | Enables | Without it |
|---|---|---|
| `DATABASE_URL` | Tiger Data / TimescaleDB hypertables | local SQLite |
| `FINCHNODE_API_KEY` | FinchNode sandbox | FinchNode public demo API (no key) |
| `GEMINI_API_KEY` | Gemini-written visit report | deterministic template report |
| `ELEVENLABS_API_KEY` | ElevenLabs voice prompts | Windows SAPI voice |
| `PHOTON_PROJECT_ID`, `PHOTON_PROJECT_SECRET`, `CAREGIVER_PHONE`, `PATIENT_PHONE` | iMessage alerts + replies | messages logged as not sent |
| `AGENT_SEED` | stable Fetch.ai agent address | generated once into `agent/.seed` |
| `QUIET=true` | mute wrist + laptop audio | |
| `DEMO_MODE=true` | replay if the device disconnects | |

## How it works
- **Wrist** (`taptrack/bridge.py`): blue starts a check, red logs a dose, gray cancels, yellow/green are the tap
  test. One instruction per screen, a spoken prompt, the 7 LEDs as a countdown and progress bar, then the exact
  score is spoken and the screen shows the word (Good / Lower than usual / Much lower). Passive tremor is
  sampled between checks when the wrist is still.
- **Metrics** (`taptrack/metrics.py`, numpy/scipy): flips/s, amplitude and decrement; tremor RMS with a
  3-12 Hz dominant frequency (the accel streams ~80 Hz when worn, see HARDWARE_NOTES.md); tap rate, rhythm CV and
  decrement; voice loudness and stability. Composite 0-100 vs the patient's own baseline (85 = baseline).
- **Storage**: TimescaleDB hypertables or SQLite. **API + websocket**: FastAPI, live events to the dashboard.
- **Dashboard**: clinician view (today's curve with doses, dose-response curve, 14-day heatmap by hours since
  dose, per-test breakdown, live panel, visit report, patient record, agent activity) and caregiver view.
- **FinchNode**: patient record + medications from the public demo API; each check is queued as a FHIR
  Observation (FinchNode is read-only). **Gemini**: neurologist report + plain-language summary, patterns only,
  with a guard that strips medication advice.
- **Fetch.ai** (`agent/`): `taptrack-care` (Agentverse mailbox, ASI:One chat) decides when to act; it asks
  `taptrack-clinic` for a follow-up slot. **Photon** (`photon/sidecar.mjs`): iMessage to caregiver and patient,
  and two-way replies ("how is she today?").

## 3-minute demo script
**0:00 The problem (20 s).** "Most people with Parkinson's take levodopa four times a day, and it wears off
before the next dose. Neurologists adjust timing from memory at visits months apart."

**0:20 On the wrist (80 s).** Strap the FREE-WILi on a judge. The home screen shows the button legend.
1. Press **red**: "Dose logged" screen; the dose marker appears on the dashboard.
2. Press **blue**: the wrist says each instruction. Flip the hand 10 s, hold still 20 s, tap yellow/green 10 s,
   say "ahhh" 5 s. The LEDs count down and fill as progress.
3. The wrist speaks the score and shows the word. On the projector the live panel fills in as each test ends,
   and the new point lands on today's curve.

**1:40 The pattern (40 s).** Switch to the 14 days. "Every dot is tagged with time since dose. Scores peak
1 to 2.5 hours after a dose and fall about 45 points by 3 to 4 hours: that is wearing-off, visible for the
first time." Show the heatmap, then click **Generate visit report**: one page for the neurologist, a plain
summary for the patient, patterns only, never dose advice.

**2:20 The agent (30 s).** Click **Simulate wearing-off check**. A low score arrives and the caregiver's phone
buzzes with an iMessage (score, usual, hours since dose). Reply "today" to get a summary back. Show the agent
feed: it already sent the report to the clinic agent and got a follow-up slot. Optionally ask it in ASI:One.

**2:50 Close (10 s).** "Parkinson's changes hour by hour, but neurologists see it a few times a year. TapTrack PD
shows them the hours they're missing."

Backup: if the device disconnects, `DEMO_MODE` switches to the simulated wrist and the dashboard keeps updating.

## Tests
```bash
.venv/Scripts/python -m pytest -q          # metrics on synthetic signals, pipeline, API, report guard, notify
.venv/Scripts/python scripts/e2e_live.py --start   # browser waits for a live check over the websocket
```

## Repo map
`taptrack/` app · `static/` dashboard · `screens/` wrist screen designs (SVG for Figma, PNG, FWI) ·
`agent/` Fetch.ai agents · `photon/` iMessage sidecar · `scripts/` setup and tools · `tests/` ·
`HARDWARE_NOTES.md` measured device facts · `PROGRESS.md` status · `SUBMISSION.md` submission steps
