# Add events to Google Calendar from the Care dashboard

Date: 2026-11-22 · Branch: `ui` · Size: small change

## Why

Lark already reads the connected Google Calendar ("Next on your calendar"). The caregiver
also wants to put things *into* that calendar, such as a doctor appointment or a visit,
from the Care dashboard, without opening Google Calendar.

## Goals

- A caregiver can create a timed event in the connected Google Calendar from `/manage`.
- They see right away that it worked, and can open the event in Google Calendar.

## Non-goals

- Margaret adding events (her screen stays simple).
- Editing or deleting events, all-day events, repeating events.
- Inviting guests: no emails from Google to other people.
- Walks being logged to the calendar automatically.

## Approaches considered

- **A. Caregiver "Add to calendar" card on `/manage`.** **Picked by the user.** It's the
  clearest use and doesn't clutter the calendar.
- B. Every walk is written to the calendar automatically. Rejected: dozens of test walks
  would fill the real calendar.
- C. "Add to calendar" on both dashboards. Rejected: more to build, and an extra button on
  Margaret's simple screen.

## Design

**Permission.** Add the Google scope `https://www.googleapis.com/auth/calendar.events` (create
and edit events) next to the existing `calendar.readonly`. Whoever already connected Google must
click **Connect Google** once more to approve it. Until then, the card says
"Reconnect Google to allow adding events" with the Connect Google button.

**Backend.** `POST /api/google/calendar/events`, signed-in session only (same cookie as the
other Google routes). Body: `title` (1–100 characters), `start` (ISO 8601 date-time with the
browser's UTC offset), `duration_min` (15–480, default 60), `note` (optional, up to 500
characters). It creates the event in `GOOGLE_CALENDAR_ID` (`primary` today), clears the cached
"next event", and returns `{title, start, end, link}` where `link` is Google's link to the event.
Errors: no session → 401; missing scope → 403 `calendar_write_not_allowed`; bad input → 422;
Google failure → 502 with a plain message. Google's `events().insert` goes behind an injectable
function, like the existing Gmail and Calendar helpers, so tests run without Google.

**Care dashboard card** (`/manage`, next to "Send a reminder"):

```
┌ Add to calendar ───────────────────────────┐
│ What        [Doctor appointment          ] │
│ Date [2026-11-25]  Time [10:00]  Length [1 hour ▾] │
│ Note (optional)                             │
│ [                                         ] │
│ [ + Add to calendar ]                       │
│ ✓ Added: Doctor appointment, Wed Nov 25 · 10:00 AM · Open in Google Calendar │
└─────────────────────────────────────────────┘
```

Length choices: 30 min, 1 hour, 2 hours. The card follows the existing Golden Hour look (pill
button, cream fields). Times are in the browser's time zone. After saving, the form clears and the
"Next on the patient's calendar" card refreshes; it changes only if the new event is the soonest.

## Constraints

- Only the approved Google account (`GOOGLE_ALLOWED_ACCOUNT_EMAIL`) can connect, so events go
  into that one account's calendar.
- The card only works in the browser that connected Google (the session cookie).

## Left to the builder

Exact copy and styling details, form validation messages, and test layout, following the
existing patterns in `accounts_api.py`, `google_services.py` and `CareScreens.jsx`.
