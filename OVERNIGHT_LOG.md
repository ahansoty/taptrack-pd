# Overnight log (Oct 4, 2026)

_Morning summary goes here when the night is done._

## Decisions and progress (chronological)

- 02:35 Started on branch `overnight-polish` from main `00dd02d`. Working tree was clean.
- 02:36 Set `DEMO_MODE=false` in `.env`. Judging uses plain `./start.sh` (no demo). With it off: no simulated replay if
  the wrist unplugs, and the caregiver is only texted for "Much lower" checks (not after every check), and the agent's
  follow-up cooldown is 7 days. Reason: matches the stated judging setup and avoids texting on Good checks.
- 02:36 While testing overnight I run the stack with `--no-photon` so no iMessage can be sent by accident
  (2-message budget). Photon is re-enabled at the end for the final configuration.
- 02:40 Hands-free device check passed: all 15 wrist screens display (show_gui_image Ok), LED countdown / progress /
  result colors OK, beep + welcome prompt play. Device holds harmless leftover test files (cal.fwi, t8k/t16k/t22k.wav,
  v08..v44.wav); left in place (no deleting).
- 02:50 Tests 49/49 pass; e2e_live passes (live result over websocket in 58 s; agent alerted on the low check, text not
  sent because Photon was deliberately off).
- 02:55 Fixed "(s)" plurals and "1 checks" in caregiver/ASI:One chat replies; friendlier "iMessage service is offline"
  error. Added a test proving a Good or Lower-than-usual check never triggers an alert outside demo mode.
- 02:58 UI audit script (scripts/ui_audit.py): sign-in validation, both roles, role redirect, report, test message,
  FinchNode card, phone width. Only real finding: old activity-log entries saved before the plural fix still read
  "dose(s)"; left as-is (no deleting stored data); they scroll out as new activity arrives.
- 03:05 Fixed: /api/status took 3.1 s (refused-connection probe to the iMessage service on Windows) -> cached with a
  short timeout, now 0.25 s. This was why the caregiver page sat on "Loading..." for a few seconds.
- 03:08 Verified the care agent answers chat-protocol messages routed through Agentverse (the ASI:One path) with real
  data (agent/test_chat.py): "Today: 5 checks, average 60. Latest at 2:40 AM was much lower than usual (33)..."
- 03:12 Labeled synthetic data on both dashboards; added `?date=YYYY-MM-DD` day view to the clinician page (used for the
  video, since "today" is empty at night). Legacy "(s)" in old activity entries tidied on display only (no data edits).
- 03:15 Found and fixed a stray backspace character inside a regex (escaping accident); added a test that fails if any
  source file contains control characters. UI audit: no problems found.
