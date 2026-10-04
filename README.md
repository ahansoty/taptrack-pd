# TapTrack PD

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**Parkinson's changes hour by hour, but neurologists see it a few times a year. TapTrack PD shows them the hours they're missing.**

A FREE-WILi on a watch strap runs a short motor check several times a day (hand flips, tremor, alternating taps,
voice), tags every result with the time since the last levodopa dose, and turns the data into a dose-response picture
for the neurologist. A care agent acts on the pattern: it texts the caregiver, reminds the patient, and sends the
neurologist a visit report with a follow-up request.

_Decision support for clinicians. Not a diagnostic device. All patient data shown is synthetic._

Website: https://taptrack.tech · Care agent: [chat on ASI:One](https://asi1.ai/invite?channelInviteKey=JmTURpQsNJq4W4uO5JbBX7TtstiDyrWyBcQB16qkvSk) · [Agentverse profile](https://agentverse.ai/agents/details/agent1q0m06w5n433l7wlefgjw5pmvu0eweuepj3trmgp926wwn7wykjefs3pj0n2/profile)

## Agents (Fetch.ai)
| Agent | Role | Address |
|---|---|---|
| `taptrack-care` | Care-team agent: Agentverse mailbox, Agent Chat Protocol, discoverable in ASI:One | `agent1q0m06w5n433l7wlefgjw5pmvu0eweuepj3trmgp926wwn7wykjefs3pj0n2` |
| `taptrack-clinic` | Simulated clinic scheduling agent; answers `FollowUpRequest` with a `FollowUpOffer` | `agent1qtnz8722nfr5vqsjd3qdwwgevuwnu4d3e5lvgcywnavd2j8xnvycyfsp8px` |

## Run it
```bash
./start.sh        # first run installs everything; Ctrl+C stops all processes
```
This starts the FastAPI server and wrist bridge (FREE-WILi on USB), the Photon iMessage sidecar, and the Fetch.ai
agents. Open http://127.0.0.1:8000, sign in with any email and pick **Clinician** or **Caregiver** (demo-grade sign-in,
no password; caregivers only see the caregiver view).

Requirements: Python 3.11+, Node 20+ (iMessage sidecar), ffmpeg (only to regenerate voice prompts), a FREE-WILi on USB.

### One-time device setup
```bash
python screens/design.py --fwi && python scripts/upload_screens.py   # 15 full-screen 320x240 images
python scripts/make_audio.py --upload                                # spoken instructions + beeps (8 kHz)
```
Uploads are content-hashed, so later starts only send changed files, and nothing uploads during a test.
The FREE-WILi plays every WAV at 8 kHz and has no volume control, so prompts are generated at 8 kHz and scaled to
`VOLUME` (0.55). Change it with `VOLUME=0.7` in `.env`, then `python scripts/make_audio.py --volume-only` and restart.

### Configuration (`.env`; every integration degrades gracefully without its key)
| Env var | Enables | Without it |
|---|---|---|
| `DATABASE_URL` | TimescaleDB hypertables (we use Neon Postgres with the TimescaleDB extension) | local SQLite |
| `FINCHNODE_API_KEY` | FinchNode sandbox (uses the first consented sandbox patient) | FinchNode public demo record |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini-written visit report | deterministic template report |
| `ELEVENLABS_API_KEY` | ElevenLabs voice prompts | Windows SAPI voice |
| `PHOTON_PROJECT_ID`, `PHOTON_PROJECT_SECRET`, `CAREGIVER_PHONE`, `PATIENT_PHONE` | iMessage alerts and replies | messages logged as not sent |
| `AGENT_SEED` | fixed Fetch.ai agent address | generated once into `agent/.seed` |
| `VOLUME`, `FW_WAV_RATE` | wrist audio level (0.55) and rate (8000) | |
| `QUIET=true` | mute all wrist and laptop audio | |

## How it works
- **Wrist** (`taptrack/bridge.py`): shows the main screen whenever idle. Red logs a dose ("Dose logged" for 3 s),
  blue starts a check, gray cancels, yellow/green are the tap test. Each test has one instruction screen, a spoken
  prompt, "Get ready", an LED countdown and an LED progress bar. After the last test: "Calculating" (about a second),
  then the result word (Good / Lower than usual / Much lower) while the exact score is spoken. The result stays for
  60 s or until any button press, then the main screen returns. Passive tremor is sampled between checks when the
  wrist is still.
- **Metrics** (`taptrack/metrics.py`, numpy/scipy): flips/s, amplitude and decrement; tremor RMS and dominant
  frequency (3-12 Hz; the accelerometer streams 80-135 Hz when worn); tap rate, rhythm variability and decrement
  (device timestamps); voice loudness and stability. Composite 0-100 against the patient's baseline (85 = baseline).
- **Storage**: TimescaleDB hypertables in their own `taptrack` schema (auto-reconnect), or SQLite.
  **API**: FastAPI with a websocket that pushes each result live.
- **Dashboard**: clinician view (latest check, 14-day pattern, today's curve with dose markers, dose-response curve,
  daily heatmap, per-test breakdown, live panel, visit report, FinchNode patient record, agent activity) and caregiver
  view. `/?date=YYYY-MM-DD` shows a past day.
- **FinchNode**: patient record and medications from the FinchNode API (public demo patient
  `patient-demo-polypharmacy`, Harriet Lindqvist, synthetic). FinchNode is read-only, so each check is queued locally
  as a FHIR Observation.
- **Gemini**: one-page neurologist report and plain-language patient summary from computed numbers only; a guard removes
  any sentence that reads as medication advice.
- **Fetch.ai** (`agent/`): `taptrack-care` (Agentverse mailbox, Agent Chat Protocol, ASI:One) checks the API every
  3 s. A "Much lower" check texts the caregiver; a recently missed check reminds the patient; a wearing-off pattern
  makes it generate the report and ask `taptrack-clinic` (a simulated clinic scheduling agent) for a follow-up slot
  (at most once a week, or on request in chat).
- **Photon** (`photon/sidecar.mjs`, spectrum-ts, cloud iMessage): sends the texts and answers caregiver replies such
  as "today" from the data, keeping context per person. It refuses dose questions.

## 3-minute demo script
**0:00 The problem (20 s).** "People with Parkinson's often take levodopa several times a day, and each dose can wear
off before the next. Neurologists adjust timing from memory at visits months apart."

**0:20 On the wrist (80 s).** Strap the FREE-WILi on a judge. The main screen shows the button legend.
1. Press **red**: "Dose logged"; the dose marker appears on the dashboard.
2. Press **blue**: the wrist speaks each instruction. At "Get ready" press blue again; LEDs count down. Flip the
   hand 10 s, hold still 20 s, tap yellow/green 10 s, say "ahhh" 5 s.
3. "Calculating", then the result word on the wrist while the score is spoken. On the projector the live panel fills
   in test by test and the point lands on today's curve with the same score.

**1:40 The pattern (40 s).** "This is a simulated patient's last 14 days. Every check is tagged with time since dose.
Scores peak 1 to 2.5 hours after a dose and fall about 45 points by 3 to 4 hours: the wearing-off window." Show the
heatmap, then **Generate visit report**: a page for the neurologist and a plain summary for the patient, patterns only.

**2:20 The agent (30 s).** Click **Simulate wearing-off check** (a simulated low check, about a minute). When it lands,
the caregiver phone gets an iMessage with the score, the usual, and hours since dose. Reply "today" for a summary. In
ASI:One ask the agent "Send the visit report": it sends the report to the clinic agent and the follow-up slot appears
in the agent feed and as a text.

**2:50 Close (10 s).** "Parkinson's changes hour by hour, but neurologists see it a few times a year. TapTrack PD shows
them the hours they're missing."

If the wrist misbehaves, "Simulate wearing-off check" and the simulated 14-day history still show the full flow.

## Tests
```bash
.venv/Scripts/python -m pytest -q                  # 51 tests: metrics, scoring, pipeline, API, sign-in, report guard, notify, watch flow
.venv/Scripts/python scripts/e2e_live.py --start   # browser waits for a live check over the websocket
.venv/Scripts/python scripts/ui_audit.py           # clicks through both dashboards, flags broken text/layout
agent/.venv/Scripts/python agent/test_chat.py "How is she doing today?"   # chat with the agent via Agentverse
```

## Repo map
`taptrack/` app · `static/` dashboard · `screens/` wrist screen designs (SVG for Figma, PNG, FWI) · `agent/` Fetch.ai
agents · `photon/` iMessage sidecar · `scripts/` setup and tools · `video/` demo video build · `docs/` taptrack.tech ·
`tests/` · `HARDWARE_NOTES.md` measured device facts · `REPORT.md` project report · `SUBMISSION.md` submission steps
