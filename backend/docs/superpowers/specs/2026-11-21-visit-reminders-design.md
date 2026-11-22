# Visit reminders from Google Calendar — short design

Date: 2026-11-21. Status: approach chosen by the user ("A: the guest list"), building.

## Intent

Margaret has memory difficulties, so a visitor arriving can surprise or confuse her. Twenty minutes
before a visit in her Google Calendar, her phone shows who is coming (photo, name, relationship),
when they arrive and why, with a **Read aloud** button.

## Approaches

- **A. Guest list (chosen by the user).** A timed event is a visit when one of its guests is a
  trusted contact. Photo and relationship come from that contact; the reason from the event title
  and description. Family only has to invite themselves. Doesn't work for visitors who aren't contacts.
- B. Title keyword ("Visit: Anna – groceries"). Fragile spelling; photo matched by name.
- C. A separate "Visits" calendar. Cleanest split, one more setup step.

## Goals / non-goals / anti-goals

- Goal: reminder visible from 20 min before the visit until it starts (+ a grace period), readable aloud.
- Non-goals: push notifications, editing the calendar (scope is `calendar.readonly`), visitors who
  aren't trusted contacts, recurring-reminder settings UI.
- Anti-goals: showing non-visits (all-day stays, her own appointments); breaking offline mode or the
  page when Google isn't connected; hammering the Calendar API from a polling page.

## Decided

- Visit = event on the **primary** calendar, not cancelled, with a start **time** (all-day events are
  skipped), whose guests include a trusted contact (email match, case-insensitive) who hasn't
  declined. Margaret herself (the calendar owner) is never the visitor.
- Several contact guests → the lowest priority number is the main visitor; the rest are listed as
  "coming with".

## Claude's calls (overridable)

- `GET /api/reminders` returns visits in the next 24 h, each with `show_now` (true from 20 min before
  the start until 30 min after it), the visitor's name / relationship / photo, `arrives_at`, a
  ready-made `arrival_text` ("3:30 PM", in the calendar's own time zone), `reason`, and the
  sentence to read aloud. Not configured / not connected → `{"available": false, "reminders": []}`.
- Reason: event title, plus the description with HTML stripped, capped at 200 characters.
- Calendar results cached for 60 s, so a page polling every minute makes ≤ 1 API call per minute.
- Env: `VISIT_REMINDER_LEAD_MIN=20`, `VISIT_REMINDER_GRACE_MIN=30`.
- UI: a reminder card at the top of "Margaret's phone" on `viewer/live-map.html`, separate from the
  check-in bubbles. Large photo (initials if none), "Anna, your daughter, is coming at 3:30 PM",
  the reason, **Read aloud** (browser speech, no new dependency) and **Got it** (hides that visit on
  this browser). The page polls every 60 s. No automatic speech (browsers block it without a click).
- Tests use a fake calendar fetch and a fake clock; no live Google in the test suite.

## Addition: calendar event emails (requested by the user, 2026-11-21)

Every timed event in the calendar (not only visits) also sends **one email to Margaret's own
Gmail**, 20 min before it starts (`VISIT_REMINDER_LEAD_MIN`): what, when, who (trusted contacts
with their relationship first, other guests by Google name or email; Margaret and declined guests
left out), where, and the description. Recipient chosen by the user ("go" on Margaret herself).

Claude's calls: once per event and start time (a moved event is emailed again); all-day,
cancelled and already-started events skipped; a failed send is logged, not retried; logged in
`notifications_sent` with no escalation (the code checks for repeats, since the unique key
ignores NULLs); `CALENDAR_EMAILS=off` turns it off; `POST /api/reminders/email-now` runs it on demand;
the existing background timer runs it every `ESCALATION_TICK_S`. Code: `app/event_emails.py`.
