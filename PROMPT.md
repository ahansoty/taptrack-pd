# Paste these into Claude Code, one at a time

Put CLAUDE.md, hw_test.py, requirements.txt, and .env.example in your project folder first. Claude Code reads CLAUDE.md automatically.

---

## Prompt 1: kickoff (paste after running hw_test.py)

Read CLAUDE.md. I ran hw_test.py and here is the output:

[PASTE hw_test.py OUTPUT HERE]

Based on the real accelerometer rate and what worked, build Phase 2: the device bridge.
- A Python module that owns the FREE-WILi connection and runs the guided daily check (hand flip, tremor, alternating taps, voice) with screen text, tones, and LEDs.
- Red button logs a dose at any time.
- Compute the metrics in CLAUDE.md with numpy/scipy. Put the metric math in its own module with unit tests on synthetic signals.
- Composite 0 to 100 score vs personal baseline; LEDs green/yellow/red; speak the score.
- Passive tremor sampling between tests.
- Store everything (raw summaries, metrics, dose events, time since last dose) via a storage layer: TimescaleDB if DATABASE_URL is set, else SQLite.
- FastAPI server exposing the data plus a websocket that pushes each new result live.
Stop and tell me how to test it.

---

## Prompt 2: synthetic data

Build Phase 3: a generator for 14 days of one patient on levodopa 4 times a day (8 AM, 12 PM, 4 PM, 8 PM). Scores rise 30 to 60 minutes after each dose, plateau, then decline about 3 hours after, dipping before the next dose. Add realistic noise, a slight downward trend over 14 days, and a few missed tests. Load it into the same storage. Stop and show me summary stats.

---

## Prompt 3: dashboard

Build Phase 4: the web dashboard served by the FastAPI app.
- Clinician view: today's curve with dose markers, a 14-day heatmap of score by hour since dose, per-test breakdown, and a live panel that updates over the websocket the moment a test finishes on the wrist.
- Caregiver view: today's status and missed tests.
- Clean, calm, highly readable clinical design. Large type, color is never the only signal, keyboard accessible.
- Footer: "Decision support for clinicians. Not a diagnostic device."
Stop and tell me how to test it.

---

## Prompt 4: ElevenLabs on the wrist

Build Phase 5a: a setup script that uses ElevenLabs to generate each spoken test instruction, converts to mono 16-bit .wav (try a modest sample rate, make it configurable), uploads with send_file using 8.3 names (flip.wav, tremor.wav, taps.wav, voice.wav, done.wav), and plays them from the device during the check. Fall back to laptop playback if upload or playback fails.

---

## Prompt 5: FinchNode and Gemini

Build Phase 5b. Here are the FinchNode API docs:

[PASTE FINCHNODE DOCS HERE]

- Load the patient record and medication schedule; use the schedule for dose times.
- Write each completed check back to the patient record.
- Gemini: a one-page neurologist report (wearing-off pattern, times of day, trend) and a plain-language patient summary. Patterns only, never dose advice. Add a "Generate visit report" button to the dashboard.

---

## Prompt 6: Fetch.ai agent

Build Phase 6. Here is the Fetch.ai hackpack:

[PASTE https://www.fetch.ai/events/hackathons/mhacks-2026/hackpack CONTENT HERE]

Create a uAgent registered on Agentverse and discoverable through ASI:One. It reads the latest data from our API and takes action: sends the visit report to the neurologist, requests a follow-up appointment when a wearing-off pattern appears, and sends a reminder when tests are missed. Follow their hackpack exactly for registration and the ASI:One submission.

---

## Prompt 7: demo hardening

Add DEMO_MODE replay, a one-command start script, and a README with setup steps and a 3-minute demo script. Run every test and fix anything broken.
