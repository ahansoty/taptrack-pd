# TapTrack PD demo video: narration script

Length 3:17. Voice: Matilda (ElevenLabs premade: knowledgeable, professional). Rebuild: `python video/build.py`.
All patient data is synthetic. Decision support only; no dose advice.

## 0:00 The problem
_Visual: html:hook_  
- **0:00.7** Parkinson's changes hour by hour, but neurologists see it a few times a year.
- **0:05.3** TapTrack PD shows them the hours they're missing.

## 0:09 The wearable
_Visual: html:watch_  
- **0:09.9** TapTrack PD runs on a FREE-WILi, worn on the wrist.
- **0:13.4** When a dose is taken, the patient presses red, so every later check knows the time since that dose.
- **0:21.0** Pressing blue starts a check that takes about a minute. The watch speaks each step, in a voice made with ElevenLabs.
- **0:32.6** Ten seconds of hand flips. Twenty seconds holding still, to measure tremor. Ten seconds of alternating taps. And five seconds of a steady ahh.
- **0:42.7** Before each test, the seven lights count down, then fill up while it records.
- **0:47.6** After a moment of calculating, the screen shows the result in words, and the exact score is spoken aloud.

## 0:54 Live on the dashboard
_Visual: split:watch+dashboard_live_  
- **0:55.4** Each test streams over USB to the TapTrack hub, which measures flip speed, tremor strength and frequency, tap rhythm and voice.
- **1:03.8** Every score is compared with the patient's own baseline, so eighty-five means a usual day.
- **1:18.7** As each test finishes, it appears on the clinician dashboard, and the final score lands on today's curve, live.
- **1:26.4** The caregiver sees the same day in plain words: how things look, the last dose, and any missed checks.

## 1:34 The pattern
_Visual: rec:pattern_  
- **1:35.2** This is a simulated patient's last two weeks, with her record pulled from FinchNode.
- **1:40.2** Every check is tagged with the time since the last dose. Scores peak one to two and a half hours after a dose, and fall by about forty-five points by hour four.
- **1:50.1** That's the wearing-off window, measured instead of remembered.
- **1:53.5** One click asks Gemini for a visit report for the neurologist and a plain summary for the patient. It describes patterns only, and never gives dose advice.

## 2:03 The care agent
_Visual: rec:agent+phone_  
- **2:04.3** A care agent built with Fetch.ai watches every check.
- **2:19.7** When a check comes back much lower than usual, it texts the caregiver over iMessage through Photon, with the score and the time since the last dose.
- **2:29.3** The caregiver can text back to ask how the day is going.
- **2:34.0** When a wearing-off pattern appears, it sends the visit report to the clinic's scheduling agent and gets a follow-up slot.
- **2:41.1** And the care team can ask the agent directly, on ASI:One.

## 2:49 How it's built
_Visual: html:stack_  
- **2:50.2** Under the hood: the FREE-WILi wearable, ElevenLabs voice, TimescaleDB on Neon, FinchNode records, Gemini reports, Fetch.ai agents, Photon iMessage, screens exported for Figma, and the site at taptrack dot tech.

## 3:08 Close
_Visual: html:close_  
- **3:09.2** TapTrack PD. The hours between visits, in front of the neurologist.

## Footage slots
- `video/footage/wrist_a.mp4`: real wrist footage shown in the wearable scene (box on the right).
- `video/footage/wrist_b.mp4`: real wrist footage replacing the animated watch beside the live dashboard.
Drop the files in and run `python video/build.py`.
