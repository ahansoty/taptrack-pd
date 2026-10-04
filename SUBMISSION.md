# Submission checklist (MHacks 2026)

Devpost deadline: **Sunday Oct 4, 12:00 PM**. Judging 12:30 to 2:30 PM.

## Fetch.ai: ASI:One Agent Challenge
Source: https://www.fetch.ai/events/hackathons/mhacks-2026/hackpack (read 2026-10-03)

Requirements we meet:
- [x] Agent registered on Agentverse (`taptrack-care`, mailbox agent)
- [x] Agent Chat Protocol (`AgentChatProtocol 0.3.0`, `uagents==0.25.5`, `publish_manifest=True`)
- [x] Discoverable and usable through ASI:One (README with keywords + example prompts, `publish_agent_details=True`)
- [x] Meaningful tool execution: reads the TapTrack API, generates the visit report, sends iMessages via Photon
- [x] Multi-agent: `taptrack-care` sends `FollowUpRequest` to `taptrack-clinic`, which replies with a `FollowUpOffer`
- [x] Innovation Lab badges in `agent/README.md` and the repo README
- [ ] Public GitHub repo with README listing agent names + addresses (you: push the repo, then paste addresses below)
- [ ] 3 to 5 minute demo video
- [ ] Registered through the MHacks ASI:One Submission Agent
- [ ] Devpost submission

### 1. Run the agent and connect the mailbox (one time)
```bash
./start.sh                                   # or: start the server, then:
agent/.venv/Scripts/python agent/taptrack_agent.py
```
The log prints both addresses and an **Agent inspector** link. Open it, click **Connect**, choose **Mailbox**.
The log then says the mailbox is registered in Agentverse. Keep the process running during judging.

In the Inspector, open **Agent Profile** and set:
- Name/handle: `taptrack-care` (handle e.g. `@taptrack-pd`)
- Description: "Parkinson's wearing-off monitor: texts caregivers on red wrist checks, reminds missed tests,
  sends the neurologist visit report and books a follow-up. Decision support only."
- Keywords: Parkinson's, levodopa, wearing-off, caregiver, neurology, wearable, iMessage

Agent addresses (fill in from the startup log):
| Agent | Address |
|---|---|
| taptrack-care | `agent1q0m06w5n433l7wlefgjw5pmvu0eweuepj3trmgp926wwn7wykjefs3pj0n2` (from this machine's seed; recheck the log) |
| taptrack-clinic | printed at startup |

### 2. Test in ASI:One
From the agent profile click **Chat with Agent** (opens chat.asi1.ai), or search ASI:One for "TapTrack Parkinson's".
Try: "How is my mom doing today with her Parkinson's checks?", "and yesterday?", "Send the visit report to her
neurologist", "Remind her about the missed check". Copy the **shared chat URL** for the submission (bonus points).

### 3. Register with the MHacks Submission Agent
1. Open https://asi1.ai/auth/signup?returnTo=%2Ffestival%2Fmhacks2026%2Fdashboard%3Futm_source%3Dmhacks2026
   (promo for 1 month ASI:One Pro + Agentverse Premium: `MHACKS26MHACKS26AV`).
2. Team lead: chat with **"MHacks Submission Agent"**, click **Create team (I'm the lead)**, enter project name
   (TapTrack PD), your name, email, team size, the problem ("Parkinson's medication wears off between doses;
   neurologists only see patients a few times a year"), and the **public GitHub URL**.
   Add the demo video, the agent profile URL and the shared ASI:One chat URL.
3. Confirm to get a **Team ID**. Each teammate chats with the same agent, clicks **Join with Team ID**.
4. Status shows "Submitted" once everyone has joined.

### Paste into the MHacks Submission Agent
- **Project name:** TapTrack PD
- **Problem it solves:** Most people with Parkinson's take levodopa several times a day, and each dose wears off
  before the next. Neurologists adjust timing from patient memory at visits months apart. TapTrack PD measures
  motor function on the wrist several times a day, tags every result with time since the last dose, and its
  Fetch.ai agent turns that into action: it texts the caregiver when a check scores red, reminds the patient about
  missed checks, and sends the neurologist a visit report with a follow-up request when a wearing-off pattern
  appears. Decision support only, never dose advice.
- **GitHub:** https://github.com/ahansoty/taptrack-pd
- **Agent profile:** https://agentverse.ai/agents/details/agent1q0m06w5n433l7wlefgjw5pmvu0eweuepj3trmgp926wwn7wykjefs3pj0n2/profile
- **Shared chat URL:** https://asi1.ai/invite?channelInviteKey=JmTURpQsNJq4W4uO5JbBX7TtstiDyrWyBcQB16qkvSk
- **Demo video:** (link once uploaded)
- **Website:** https://taptrack.tech

### 4. Devpost
Repo link, 3 to 5 min video, agent names + addresses, and the Fetch.ai track selected.

## Photon (iMessage)
- [ ] Project at https://app.photon.codes, `PHOTON_PROJECT_ID` / `PHOTON_PROJECT_SECRET` in `.env`
- [ ] Caregiver + patient numbers in `.env` (`CAREGIVER_PHONE`, `PATIENT_PHONE`, E.164) and registered under
      **Users** in the Photon dashboard (free/pro plans only message registered users)
- [ ] Each phone texts the project's iMessage line once (Photon's deliverability advice)
- [ ] Ask the Photon reps for the exact prize rules / promo code (not published for MHacks)
- Demo: dashboard "Send test message"; red check -> caregiver iMessage; caregiver replies "today" -> summary

## Other sponsors
- FREE-WILi: the wearable. Tiger Data: set `DATABASE_URL` to a Timescale service for hypertables.
- FinchNode: public demo API used live (patient record + medications); write-back queued as FHIR (API is read-only).
- Gemini: set `GEMINI_API_KEY` for the AI-written report (template otherwise).
- ElevenLabs: set `ELEVENLABS_API_KEY`, then `python scripts/make_audio.py --upload`.
- Figma: import `screens/svg/*.svg`; `python scripts/figma_sync.py` pulls edits back.
- Notability: 2 screenshots + a note on how you used it. Table number in the Devpost submission.
