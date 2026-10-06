# TapTrack PD Care Agent

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

**Parkinson's wearing-off monitor and care-team assistant.** TapTrack PD is a wrist-worn check (hand flips,
tremor, alternating taps, voice) done several times a day and tagged with time since the last levodopa dose.
This agent watches that data and acts on it:

- **Red score on a wrist check** → texts the caregiver over iMessage (Photon Spectrum) with the score, how it
  compares to the patient's usual, and hours since the last dose.
- **Missed scheduled check** → texts the patient a gentle reminder.
- **Wearing-off pattern over 14 days** → generates the neurologist visit report, sends it to the clinic's
  scheduling agent (`taptrack-clinic`) with a follow-up request, and tells the caregiver the proposed slot.

It describes patterns only. It never gives medication or dose advice.

## Ask it in ASI:One
- "How is my mom doing today with her Parkinson's checks?"
- "What about yesterday?" (keeps context)
- "Send the visit report to her neurologist"
- "Book a follow-up appointment for the wearing-off pattern"
- "Remind her about the missed check"
- "When was her last dose logged?"

## Agents
| Agent | Role | Address |
|---|---|---|
| taptrack-care | Care-team agent (mailbox, Agentverse, chat protocol) | `agent1q0m06w5n433l7wlefgjw5pmvu0eweuepj3trmgp926wwn7wykjefs3pj0n2` |
| taptrack-clinic | Clinic scheduling agent (agent-to-agent follow-up offers) | `agent1qtnz8722nfr5vqsjd3qdwwgevuwnu4d3e5lvgcywnavd2j8xnvycyfsp8px` |

Protocols: AgentChatProtocol 0.3.0 (ASI:One), custom `FollowUpRequest` / `FollowUpOffer` models between agents.

Keywords: Parkinson's disease, levodopa, wearing-off, motor fluctuations, wearable, neurology, caregiver,
remote monitoring, decision support, iMessage, health.

_Decision support for clinicians. Not a diagnostic device._
