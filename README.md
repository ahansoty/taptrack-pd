# TapTrack PD

Wrist-worn Parkinson's wearing-off tracker. FREE-WILi on a watch strap + clinician dashboard.

## Start here
1. `python -m venv .venv` and activate it
2. `pip install -r requirements.txt`
3. `cp .env.example .env` (fill keys later)
4. Plug in the FREE-WILi and run `python hw_test.py`
   Optional audio test: `python hw_test.py some_clip.wav`
5. Open Claude Code in this folder and follow PROMPT.md in order.

## 3-minute demo outline
1. The problem (20 s): doses wear off; neurologists see patients a few times a year.
2. Strap it on a judge (90 s): press red to log a dose, wrist speaks each instruction, run the check, score is spoken and shown on LEDs, result appears live on the dashboard.
3. The pattern (40 s): 14 days of data, clear decline about 3 hours after each dose, one-click neurologist report.
4. The agent (20 s): it booked a follow-up and sent the report on its own.
5. Close (10 s): "Parkinson's changes hour by hour, but neurologists see it a few times a year. TapTrack PD shows them the hours they're missing."

## Devpost checklist
- Add all teammates
- Tag Notability with 2 screenshots and a note on how you used it
- Submit the Fetch.ai agent through the ASI:One submission agent too
- Table number in the submission
- Submit before 12 PM Sunday
