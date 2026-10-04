# TapTrack PD: project report

_Status as of Sunday Oct 4, 2026, ~2 AM. MHacks 2026. Devpost deadline 12:00 PM; judging 12:30 to 2:30 PM._

> **Parkinson's changes hour by hour, but neurologists see it a few times a year. TapTrack PD shows them the hours they're missing.**

_Decision support for clinicians. Not a diagnostic device. All patient data shown is synthetic._

---

## 1. The problem and the idea

Most people with Parkinson's take levodopa several times a day (here: 8 AM, 12 PM, 4 PM, 8 PM). Each dose kicks in after
30 to 60 minutes and wears off before the next one ("wearing-off"). Neurologists adjust dose timing from what patients
remember at visits months apart.

TapTrack PD is a one-minute motor check on the wrist, done several times a day. Every result is tagged with the time since
the last dose, so two weeks of checks become a **dose-response curve** the neurologist can read in seconds. A care agent
acts on the pattern: it texts the caregiver about bad checks, reminds the patient about missed checks, and sends the
neurologist a visit report with a follow-up request.

## 2. How it works, end to end

```
 FREE-WILi on the wrist ──USB──► Bridge (Python) ──► Metrics + score ──► TimescaleDB (Neon, Tiger Data)
   buttons, accelerometer,          guided check,        numpy/scipy          │
   mic, screen, LEDs, speaker       screens, LEDs,                            ▼
                                     voice prompts                     FastAPI + websocket ──► Dashboard (clinician / caregiver)
                                                                              │                    sign-in by role
                                                                              ▼
                                      FinchNode (patient record) ◄── API ──► Gemini (visit report)
                                                                              │
                                      Fetch.ai care agent ◄── polls ──────────┘
                                        │  ├─► clinic agent (follow-up slot)
                                        └──► Photon sidecar ──► iMessage to caregiver / patient ◄── replies ("today?")
```

### 2.1 The wrist (FREE-WILi)
- **Buttons** (left to right under the screen: gray, yellow, green, blue, red): blue starts a check, red logs a dose,
  gray cancels, yellow/green are the tap test.
- **Screens**: 15 full-screen 320x240 images designed in the "clinical" theme (off-white, navy, teal; spaced-caps labels;
  status card with a colored stripe; button legend that lines up with the physical buttons). Designed as SVG frames
  (importable into Figma), rendered to PNG, converted to `.fwi`, uploaded once with a content-hash manifest.
- **Flow**: main screen whenever idle. A check runs four tests, each with an instruction screen, a spoken prompt
  (ElevenLabs), "Get ready", an LED countdown, and an LED progress bar while recording. Then "Calculating" (about a
  second), then the result **word** on screen (Good / Lower than usual / Much lower) while the **exact score is spoken**.
  The result stays for 60 seconds or until any button press, then the main screen returns. Red shows "Dose logged" for 3 s.
- **Four tests** (about one minute total):
  | Test | Signal | Metrics |
  |---|---|---|
  | Hand flips, 10 s | accelerometer | flips/s, amplitude, decrement first vs last third |
  | Hold still, 20 s | accelerometer | tremor RMS (milli-g), dominant frequency 3-12 Hz |
  | Alternating taps, 10 s | yellow/green buttons | taps/s, rhythm variability (CV), decrement, errors |
  | "Ahhh", 5 s | microphone | loudness (dBFS), stability (CV) |
- **Passive tremor** is sampled between checks when the wrist is still.

### 2.2 Measured hardware facts (HARDWARE_NOTES.md)
- Display 320x240; `show_gui_image` needs the bare filename; uploads ~25 KB/s.
- The accelerometer is **motion-gated**: ~1 sample/s lying still on a table, ~80-135 Hz when worn. So tremor frequency
  analysis works on the wrist, and a check flags "not worn" if the stream is too slow.
- USB delivers events in bursts, so tap timing uses the device's own timestamps and bursty accelerometer timing is evened out.
- The firmware's tone command fails (v54), so beeps are uploaded WAV files.

### 2.3 Scoring
Each metric is compared with the patient's **own baseline** (mean and SD from early-days ON-state checks) and mapped to
0-100 (at baseline = 85, one SD better = 100, one SD worse = 70). Tests are weighted (flips 30%, taps 30%, tremor 20%,
voice 20%) into one composite score. Good >= 70, Lower than usual 50-69, Much lower < 50.

### 2.4 Data
- **TimescaleDB** (Tiger Data) on Neon Postgres: `checks`, `doses`, `passive` are hypertables in a dedicated `taptrack`
  schema, kept separate from the other app's tables in that database. It reconnects automatically when Neon closes idle
  connections. SQLite is the fallback when `DATABASE_URL` is unset.
- **Synthetic history**: 14 days of a 78-year-old patient on levodopa four times a day. Onset ~36 min, wear-off from
  ~3 h, noise, a slight decline over 14 days, ~8% missed checks. Mean score: ~25 just after a dose, ~82 at 1-2.5 h,
  ~36 at 3-4 h. Reseeded once per day so "today" has the morning's history.

### 2.5 Dashboard and sign-in
- **Sign-in**: email plus role (Caregiver / Clinician). Demo-grade, no password, signed cookie. Caregivers only see the
  caregiver view.
- **Clinician**: latest check, 14-day tiles (wearing-off present, decline onset, checks/missed, trend), today's curve with
  dose markers, dose-response curve (mean ± SD by hours since dose), daily heatmap by hours since dose, per-test peak vs
  late, live panel over websocket, visit report, patient record, agent activity.
- **Caregiver**: status in plain words, last/next dose, missed checks today, messages sent, "Send test message".
- Same look as the wrist screens. Every chart has a table view. Colors validated for color-blind safety. Phone width OK.

### 2.6 Visit report (Gemini)
One click: a one-page neurologist report and a plain-language patient summary, from computed numbers only. A guard removes
any sentence that reads as medication advice (in testing it removed one Gemini sentence). A deterministic template is the
fallback without a key.

### 2.7 Care agent (Fetch.ai) and messages (Photon)
- `taptrack-care` (Agentverse mailbox, Agent Chat Protocol, discoverable in ASI:One) polls the API every 3 s and decides:
  - red check → caregiver iMessage (score, usual, hours since dose); in demo mode, after every check
  - missed check (within 90 min) → patient reminder
  - wearing-off pattern → generate report → `FollowUpRequest` to `taptrack-clinic` → clinic replies with a slot → caregiver
    iMessage ("report sent, follow-up Tue Oct 6, 10:30 AM")
- In ASI:One it answers "how is she doing today?", "and yesterday?", "send the visit report", "book a follow-up",
  "remind her about the missed check".
- **Photon Spectrum** sidecar (Node, `spectrum-ts`, cloud iMessage, no Mac) sends the texts and answers caregiver
  replies from our data, keeping context per person. It refuses dose questions.
- If the agent is offline, the server sends the red-score alert itself.

## 3. Sponsors: what each one does here

| Sponsor | Role in TapTrack PD | Status |
|---|---|---|
| **FREE-WILi** | The wearable: buttons, accelerometer, mic, screen, LEDs, speaker, number speech | Working; verified with real checks |
| **Tiger Data** | TimescaleDB hypertables for checks, doses, passive tremor | Working on Neon (TimescaleDB 2.24) |
| **FinchNode** | Patient record + medications; checks queued as FHIR Observations for write-back | Working (public demo record); sandbox patient needs consent; API is read-only |
| **Gemini** | Neurologist report + patient summary, patterns only | Working (`gemini-3.5-flash-lite`, ~9 s) |
| **ElevenLabs** | Spoken test instructions on the wrist (voice "Sarah") | Working; prompts on the device |
| **Fetch.ai** | Care agent + clinic agent; ASI:One chat; decides when to notify | Working; registered on Agentverse (mailbox) |
| **Photon** | iMessage alerts, reminders, two-way caregiver chat via Spectrum | Working; sends and replies verified |
| **Figma** | Wrist screens as SVG frames; `scripts/figma_sync.py` pulls edits back via the Figma API | Pipeline ready; needs `FIGMA_TOKEN` to sync |
| **.tech domain** | https://taptrack.tech (GitHub Pages, HTTPS) | Live |
| **Notability** | Screenshots + note for Devpost | To do |

## 4. What has been verified

- 49 automated tests: metrics on synthetic signals, scoring, storage, synthetic data, API, sign-in and roles, report
  guard, FinchNode parsing, notifications/chat, watch flow (result hold and dismiss), disconnect → demo replay,
  "never stuck on Calculating".
- Real device: full checks run end to end (flips 4.0/s, tremor detected at 5.5 Hz when shaken on purpose, taps, voice).
- Live pipeline: wrist → database → dashboard over websocket (~1 s after the last test).
- Agent: wearing-off → Gemini report → clinic agent offer → caregiver iMessage delivered; red check → alert delivered;
  caregiver "today" reply answered.

## 5. What still needs to be done

| # | Task | Who | Notes |
|---|---|---|---|
| 1 | Turn sound on and test the spoken prompts | You | Set `QUIET=false` in `.env`, restart, do one check |
| 2 | Morning restart before the demo | You | `./start.sh --demo` around 11 AM so today's chart has the morning |
| 3 | ASI:One test chat + shared link | You | Agent profile → Chat with Agent; copy the shared chat URL |
| 4 | MHacks Submission Agent | You | Answers to paste are in `SUBMISSION.md` |
| 5 | Demo video (3-5 min) | You | `python scripts/record_walkthrough.py` after 10 AM for B-roll; add narration + wrist shots |
| 6 | Devpost | You | Repo, video, agent names/addresses, table number, Notability screenshots |
| 7 | FinchNode sandbox consent (optional) | You | https://finchnode.com/connect/cs_83838ff6beb13e5e1792 |
| 8 | Rotate keys after the hackathon | You | GitHub token and API keys were pasted in chat |
| 9 | Second real check to confirm the tap-timing fix | You + me | Raw data saves to `data/raw/` for analysis |

Known limitations to state honestly in the pitch:
- Sign-in is demo-grade (no password); the dashboard runs on the laptop, so the website's Sign in button only works there.
- FinchNode has no write API; write-back is a local FHIR queue.
- No demo patient has a levodopa order, so dose times come from TapTrack's schedule.
- The composite score's baseline comes from synthetic data; a real deployment would calibrate per patient.

## 6. How to run

```bash
cd ~/Downloads/hackathon/taptrack-pd
./start.sh --demo            # server + wrist + iMessage sidecar + Fetch.ai agents (Ctrl+C stops all)
# App: http://127.0.0.1:8000  (sign in, pick Clinician or Caregiver)
# Site: https://taptrack.tech
.venv/Scripts/python -m pytest -q
```

3-minute demo script: README.md. Submission steps: SUBMISSION.md. Hardware facts: HARDWARE_NOTES.md.
Repository: https://github.com/ahansoty/taptrack-pd
