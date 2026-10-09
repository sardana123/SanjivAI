# 🌿 Sanjeevani - a voice-first medication companion

> Missed and doubled medicine doses are one of the most preventable causes of hospital readmission,
> especially for elderly people who live far from their families.
> **Sanjeevani** speaks reminders aloud, understands replies in **English, Hindi and Hinglish**, blocks
> accidental double doses, and **tells a caregiver when something goes wrong**. It needs no app store, no
> account and no pip packages.

Built for **UN SDG 3 - Good Health & Well-being** (IBM SkillsBuild for Academia project).
Python standard library only. Runs on a laptop, a Raspberry Pi or a cheap VPS.

![status](https://img.shields.io/badge/tests-36%20passing-brightgreen) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![deps](https://img.shields.io/badge/dependencies-0-success) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

## Screenshots

| Reminder & big buttons | Voice confirmation | Double-dose guard |
|---|---|---|
| ![reminder](docs/screenshots/01-patient-reminder.png) | ![confirm](docs/screenshots/02-voice-confirmation.png) | ![guard](docs/screenshots/03-double-dose-guard.png) |

| Hindi voice | Emergency handling | Caregiver dashboard |
|---|---|---|
| ![hindi](docs/screenshots/04-hindi-voice.png) | ![emergency](docs/screenshots/05-emergency.png) | ![dashboard](docs/screenshots/06-caregiver-dashboard.png) |

## Why it is different

| Problem with typical reminder apps | What Sanjeevani does |
|---|---|
| Small buttons, English only, needs typing | Big mic button, speaks and listens in **English and हिन्दी** (browser speech APIs, no cloud key) |
| A reminder is ignored and nobody knows | **Escalation agent**: caregiver is alerted at +45 min, and again when the dose is recorded as missed (+3 h) |
| Patient taps "taken" twice or forgets they already took it | **Double-dose guard**: refuses to record a dose too soon after the last one and says when it was taken |
| Chest pain mentioned in passing | **Emergency phrases** bypass everything: advises calling 112 and alerts the caregiver immediately |
| Caregiver gets noise, not insight | **Insights agent**: adherence %, streak, per-medicine rate, "most missed slot" and plain-language advice |
| AI chatbots can hallucinate dosing | **LLM is optional and only rewords routine replies**; it can never record, block or escalate a dose, and its output is rejected unless every number, time and medicine name survives |

## Quick start

```bash
git clone https://github.com/sardana123/sanjeevani && cd sanjeevani
python -m sanjeevani demo        # seeds 14 days of realistic history, serves on http://127.0.0.1:8000
# or an empty instance:
python -m sanjeevani serve
```

Open the page in **Chrome / Edge** (best speech support). Tick *"Speak reminders aloud"* once so the browser allows audio.
Try saying (or typing): *"I took my medicine"*, *"what's next"*, *"remind me in 20 minutes"*, *"मैंने दवा ले ली"*,
*"add vitamin c 500 mg at 9 am"*, *"I have chest pain"*.

Docker: `docker build -t sanjeevani . && docker run -p 8000:8000 -v sanjeevani-data:/data sanjeevani`

## Architecture

```
 Browser (mic + speaker, Web Speech API)         Caregiver dashboard
            │  /api/patients/{id}/talk                  │  /insights  /alerts
            ▼                                           ▼
 ┌──────────────────────── Companion (orchestrator) ───────────────────────────┐
 │  Voice agent   nlu.py: rules for EN / HI / Hinglish, emergency-first order   │
 │  Scheduler     dose events, due window, snooze, double-dose & too-early guard │
 │  Escalation    escalation.py: late → missed alerts, retries, pluggable notify │
 │  Insights      insights.py: adherence, streaks, worst time slot, summary      │
 │  Warmth (opt.) llm.py: Claude rewrites routine replies, facts verified        │
 └───────────────────────────────┬──────────────────────────────────────────────┘
                                 ▼
                        SQLite (patients, medications, dose_events, alerts)
 Background ticker (30 s) → materialise schedule → escalate → deliver alerts (console + webhook)
```

**Safety by design:** every decision that touches a patient's health is deterministic and unit-tested. The optional
LLM runs *after* the decision, on routine intents only (`taken`, `next`, `snooze`), with a fact-preservation check
and automatic fallback to the template text.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `SANJEEVANI_DB` | `sanjeevani.db` | SQLite file |
| `SANJEEVANI_HOST` / `SANJEEVANI_PORT` | `127.0.0.1` / `8000` | Bind address |
| `SANJEEVANI_TOKEN` | *(empty = open)* | If set, `/api/*` requires `Authorization: Bearer <token>` - **set this before exposing to a network** |
| `SANJEEVANI_WEBHOOK_URL` | *(empty)* | Caregiver alerts are POSTed here as JSON (n8n, Zapier, Make, Slack, Twilio/WhatsApp bridge, ntfy) |
| `ANTHROPIC_API_KEY` | *(empty = off)* | Enables warmer wording of routine replies |
| `SANJEEVANI_MODEL` | `claude-sonnet-5-5` | Model used for wording |
| `SANJEEVANI_ALERT_AFTER_MIN` | `45` | Minutes late before the first caregiver alert |
| `SANJEEVANI_MISS_AFTER_MIN` | `180` | Minutes late before a dose is marked missed |
| `SANJEEVANI_DUE_LEAD_MIN` | `30` | A dose is "due" this many minutes early |
| `SANJEEVANI_EMERGENCY_NUMBER` | `112` | Number spoken in emergencies (India: 112) |

Webhook payload:
`{"title","message","kind","patient","caregiver_name","caregiver_contact","created_at"}`.

## REST API

| Method & path | Description |
|---|---|
| `GET /api/health` | Liveness (no token needed) |
| `GET/POST /api/patients`, `PUT /api/patients/{id}` | Manage patients (language, caregiver) |
| `GET/POST /api/patients/{id}/medications`, `DELETE /api/medications/{id}` | Medicines, times as 24h `HH:MM` |
| `GET /api/patients/{id}/today` | Today's doses, `due_count`, spoken `reminder`, `next` |
| `POST /api/patients/{id}/talk` `{text, lang?}` | Natural-language command → `{intent, reply, actions}` |
| `POST /api/doses/{id}/take` `{force?}` · `/skip` · `/snooze {minutes}` | Explicit controls (`409` on guard) |
| `GET /api/patients/{id}/insights?days=14` | Adherence analytics |
| `GET /api/patients/{id}/alerts`, `POST /api/alerts/{id}/ack` | Caregiver alert inbox |

## Development

```bash
python -m unittest discover -s tests -t . -v     # 36 tests, ~1 s, no network
```

Extend it: add a language in `responses.py` + keyword tuples in `nlu.py`; add a channel by writing a class with
`send(alert, patient) -> bool` in `notify.py`.

## Limitations & roadmap

- **Not a medical device.** It never recommends, changes or interprets treatment; it reminds, records and escalates.
  Medicine schedules must be entered from a doctor's prescription.
- Browser speech recognition quality varies by browser and accent; typing and big buttons always work.
- Roadmap: prescription photo → schedule (OCR + LLM with caregiver confirmation), Twilio voice-call fallback,
  more Indian languages, refill tracking, multi-caregiver rotas, Raspberry Pi smart-speaker build.

## Project context

Lean Canvas, concept note and slides for the IBM SkillsBuild Masterclass: problem = missed medication in elderly
and remote patients; customers = elderly patients living apart from family, NRI/urban families, clinics and
community health programmes; UVP = *"A caring voice that makes sure medicine is taken, and a family that knows when it isn't."*

## License

MIT
