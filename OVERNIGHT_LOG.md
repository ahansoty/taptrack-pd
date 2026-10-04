# Overnight log (Oct 4, 2026)

## Morning summary

**Status: ready for judging.** All checks pass: 51/51 tests, live end-to-end check, and a UI audit of both dashboards. The judging setup is running right now: `./start.sh`, demo mode off, real FREE-WILi, Photon on, and both agents online.

### What's done
- **Device:** a hands-free check passed. All 15 wrist screens, the LED countdown and progress, and audio playback work. The full check flow was verified with the simulated device (score lands on the dashboard live in about 58 s).
- **Dashboards:** both roles were clicked through with the UI audit, and no problems were found.
  - Synthetic data is labeled.
  - "Decision support for clinicians. Not a diagnostic device." is visible.
  - The FinchNode record card shows the record ID and the "FinchNode · live API" label.
- **Agent:** the care agent answers through Agentverse (the ASI:One path) with real numbers.
  - A Good check never alerts outside demo mode, and a test proves it.
  - The caregiver alert for a "much lower" check was delivered to the caregiver phone overnight.
- **Website (taptrack.tech):** claims now match the system.
  - Added the "Talk to our care agent" section, the ASI:One invite, and the Agentverse profile.
  - Footer links to the source code; removed localhost links.
  - Added a video slot that stays hidden until `docs/media/demo.mp4` exists.
- **Docs:** README, REPORT, and SUBMISSION were rewritten to match the final system (agents and addresses table, plain `./start.sh`). Added a "Demo video" section.
- **Security:** scanned the full history for every .env secret, the GitHub token, and both phone numbers: 0 hits. There was one leak (the dashboard session key). It is now untracked and replaced locally. Details are in the 04:00 entry.
- **Backup video (PART 2):**
  - `demo_video.mp4`: 3:17, 1080p30, about -17 LUFS, peak -1.4 dBFS.
  - `demo_short.mp4`: 60 s.
  - `video_script.md`: timed narration.
  - One-command rebuild: `python video/build.py`. Drop real wrist clips into `video/footage/` (see the README there).
  - The video uses ElevenLabs narration with burned-in captions, real dashboard recordings, the real wrist PNGs and prompts, and generated music.
  - Placeholder boxes marked "WRIST FOOTAGE · SLOT A" are visible until you add real footage.

### What changed overnight (high level)
- Demo mode is off for judging.
- Audio is at 8 kHz and 55% volume.
- The caregiver chart now includes night-time checks.
- The agent feed shows "not delivered" with the reason on hover.
- Plural fixes ("1 check").
- `/api/status` is fast (3.1 s → 0.25 s).
- Added a `?date=` day view.
- Added `pytest.ini` so plain `pytest` collects only `tests/`.
- Added an `e2e_live.py --good` option that never sends a text.
- Branch `overnight-polish` was merged to main and pushed (see the last entry).

### What's risky
1. **The caregiver phone may not receive more texts.**
   - Photon limits a new contact until that person replies. The second overnight text was rejected: "New contact has sent 2 of 3 messages; replies are limited…".
   - **Fix:** text the TapTrack iMessage line from the caregiver phone (+1…381) before judging, and from the patient phone if you want missed-check reminders.
2. **The care agent offers the follow-up visit only once every 7 days** (demo mode is off), and it already did tonight.
   - In the demo, show it by asking ASI:One "Send the visit report to her neurologist", or point to the entry already in the feed.
3. **Old dashboard session key.** The session-signing key from the earlier commit is still in git history. It no longer works, because a new key is in use, but rotate everything after the hackathon anyway.
4. **Test files on the device.** The wrist still has leftover test files (cal.fwi, t*.wav, v*.wav). They are harmless and were not deleted.
5. **Video caveats.** The pattern scene is a simulated patient (labeled), and the phone is a mockup that shows the real message text.
   - Two of the four texts shown (the "today" reply and the report text) were produced by the system, but Photon did not deliver them to a phone overnight.
   - The video says "Phone is a mockup; the message text is exactly what the system produced."
6. **Today's data.** "Today" on the dashboard contains the overnight test checks (scores 32 and 81, among others). They are real stored checks, so they were left in place. The automatic once-a-day reseed only replaces the synthetic history.

### Needs you in the morning (do in this order, before 12 PM)
1. Text the TapTrack iMessage line from the caregiver phone (and the patient phone) to lift Photon's new-contact limit.
2. Check that `./start.sh` is still running (dashboard at http://127.0.0.1:8000). Do one real wrist check with sound, wearing the device.
3. Watch `demo_video.mp4` and `demo_short.mp4`. Optionally film the wrist, drop the clips into `video/footage/`, and run `python video/build.py` (about 15 min).
4. Upload the video to YouTube (unlisted is fine), then put the link on Devpost.
   - Optionally copy it to `docs/media/demo.mp4` and push so it appears on taptrack.tech.
5. Register with the MHacks ASI:One Submission Agent (needs your login).
6. Submit on Devpost: repo link, video link, agent addresses from README, taptrack.tech, and the ASI:One shared chat link from SUBMISSION.md.
7. Take the Notability screenshots if you want that prize.
8. Optional: FinchNode consent for a sandbox user. Without it, the public demo patient is used, which is correct and labeled.
9. After the hackathon: rotate the API keys and the GitHub token.

---

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
- 03:30 Website: corrected claims to match the system (main screen image now "Ready"; "3-5 doses"/"a few visits"/
  "~1 minute"; "simulated example patient"; report goes to the clinic's scheduling agent; example texts match the real
  message format; "designed to be worn ... docked" instead of implying it is wireless today). Removed links to
  127.0.0.1 (broken for visitors). Added demo-video slot (shows docs/media/demo.mp4 when present), footer links to source
  code and agent profile. All external links return 200; all anchors resolve. Not pushed yet (branch).
- 03:50 Docs rewritten to match the final system: README (agents + addresses table as the hackpack requires, plain
  ./start.sh, 8 kHz/55% audio, demo script that only uses real behavior), REPORT.md (sponsor accuracy: TimescaleDB
  runs on Neon not Tiger Cloud; Figma import path ready but not synced; overnight changes), SUBMISSION.md (repo,
  addresses, shared chat link). Removed --demo references.
- 04:00 SECURITY: full-history scan (33 commits, all branches) for every secret value in .env, the GitHub token and both
  phone numbers: 0 hits anywhere. .env, agent/.seed and the agent state file are ignored.
  LEAK FOUND: `data/.session_key` (the dashboard's sign-in cookie signing key) was tracked and pushed to main on
  Oct 4 (commit 14f3cfd). Impact: someone could forge a dashboard sign-in cookie for the local dashboard (demo-grade
  sign-in; no patient data beyond synthetic). Fixed: untracked + ignored, and a new key generated locally, so the
  published one no longer works. It remains in git history (no history rewrite, per your rules).
- 03:17 Final judging configuration running (`./start.sh`, demo mode off, Photon on). Recorded the agent scene.
  iMessage budget used (2 sends): #1 caregiver alert for a simulated "Much lower" check (score 32) DELIVERED.
  #2 "report sent / follow-up Tue Oct 6 10:30 AM" REJECTED by Photon: "New contact has sent 2 of 3 messages; replies
  are limited ... until they respond". => The caregiver phone must text the TapTrack iMessage line once before judging
  (see "Needs you in the morning"). Same for the patient phone if you want missed-check reminders to go through.
  No further sends overnight.
- 04:10 Video pipeline (video/build.py) written; first renders fixed (odd height, ffmpeg 8 script flag, clips a few
  frames short ended the crossfade chain early -> each clip now held/trimmed to its exact length).
- 04:20 Tests 51/51 (added pytest.ini: plain `pytest` was also collecting agent/test_chat.py, a manual script, and
  erroring). UI audit clean. e2e: ran with a Good simulated check (new `--good` flag) so no text could be sent; result
  over the websocket in 58 s, score 81. Photon log confirms no new sends.
- 04:30 Video QA: moved the "simulated" labels to the top so captions never cover them; phone subtitle now says it is
  a mockup. Narration text checked against the system (scores, times, message text copied from real output).
