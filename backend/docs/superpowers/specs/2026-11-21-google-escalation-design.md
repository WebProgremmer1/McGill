# Google connection + route-alert email escalation — design

Date: 2026-11-21. Status: draft, awaiting approval.
Scope: the shared base (Google connection, Supabase, trusted contacts) and route-alert emails.
Visit reminders (Google Calendar) are the **next** round and are out of scope here, but the base
must already request the calendar permission so the family member connects Google only once.

## Intent

The walking-safety app (Margaret, Home → Tim Hortons) already scores risk, raises on-screen
check-ins and caregiver alerts, and pushes them over SSE. Real families won't be watching a
dashboard, so alerts must reach them by **email**, escalating through a **ranked list of trusted
contacts**. A family member sets the app up once: signs in with the person's Google account and
enters the contacts.

## Goals

- One-time "Connect Google" for the person's account, done by a family member during setup.
- Trusted contacts with priority 1, 2, 3…, entered at setup, pickable from Google Contacts.
- Emails sent from the person's own Gmail, by risk tier:

| Trigger | Action |
|---|---|
| Score 30–59 (medium) | Existing on-screen check-in **plus** an email to the person ("it looks like you may have left your usual route — are you okay?") |
| Score 60–89 (high), **or** a medium check-in unanswered for 3 min | Sequential escalation: email contact #1; if nobody clicks "I'm on it" within 5 min, #2; then #3… |
| Score 90–100, help button, or no-signal alert | Email **all** contacts at once |

- A sequential escalation that later reaches 90+ (or help / no-signal) jumps to "everyone now".
- Any contact clicking "I'm on it" closes the escalation; no further emails for it.
- Escalation state survives a server restart.
- No duplicate emails (same journey + tier + recipient is sent once).

## Non-goals

- Reading Gmail. Only `gmail.send` is requested.
- SMS / push (noted as the right production follow-up; email is slow for a lost person).
- Visit reminders (next round). Calendar is only *authorized* now, not used.
- Multi-tenant auth for family members (Supabase Auth can come later; separate from Google).
- Google app verification / production publishing. The OAuth app stays in **Testing** mode.

## Anti-goals

- A Google refresh token stored in plain text, or the Supabase service key reaching a browser.
- An emergency that silently stops escalating because a timer was lost or Gmail errored.
- Spamming contacts: repeated GPS updates at the same tier must not re-send.
- Breaking offline mode: with no Google/Supabase configured, the app and its 66 tests behave as today.

## Constraints

- Existing Python/FastAPI backend in `backend/app`, in-memory journeys. Prototype, fictional users;
  every email carries the existing "not medically validated" disclaimer.
- Journey "now" is the newest GPS timestamp, but escalation delays are **wall-clock**, like the
  existing no-signal watchdog. Delays are configurable (env) so demos can use seconds.
- Localhost only: the "I'm on it" link points at `http://localhost:8000` and works on the demo machine.
- Google OAuth app in Testing mode: refresh tokens expire after 7 days → reconnect weekly.
- One person, one connected Google account for this round.

## Approaches considered

- **A. Backend owns Google OAuth (chosen).** FastAPI runs the web-server OAuth flow with
  `google-auth-oauthlib`, stores the encrypted refresh token in Supabase, calls Gmail/People/Calendar
  with `google-api-python-client`. Escalation timers run in the existing background loop with state
  in Supabase. All logic in Python next to the risk engine; fully testable with fakes.
- **B. Supabase Auth "Sign in with Google".** Quick login, but Supabase doesn't refresh Google
  provider tokens, so we'd still write refresh logic, split across frontend and backend.
- **C. Supabase pg_cron / Edge Functions for timers.** Most durable, but escalation logic would live
  in TypeScript away from the Python risk engine and be hard to test end to end.

Chosen: A, by the user, for one codebase and testability.

## Decided design

**Google OAuth**
- Scopes: `calendar.readonly`, `contacts.readonly`, `gmail.send`, plus `openid email`.
- `GET /api/google/connect` → redirect to Google consent (`access_type=offline`, `prompt=consent`,
  `state` CSRF token).
- `GET /api/google/callback` → exchange code, encrypt refresh token (Fernet, key in `.env`), upsert
  into `google_accounts`.
- `GET /api/google/status` → connected?, email, granted scopes. `POST /api/google/disconnect`.
- Access tokens are refreshed by the Google library on demand; an `invalid_grant` marks the
  account "needs reconnect" and shows in `/api/health`.

**Supabase (server-side only, service-role key)**
- `google_accounts`: id, person_name, google_email, refresh_token_enc, scopes, status, connected_at.
- `contacts`: id, name, email, relationship, priority (unique, 1..n), photo_url, source (`google`|`manual`).
- `escalations`: id, journey_id, tier (`person`|`sequential`|`all`), status (`open`|`acknowledged`|`closed`),
  next_priority, next_step_at, opened_at, acknowledged_by, ack_token_hash.
- `notifications_sent`: id, escalation_id, journey_id, recipient, kind, sent_at, gmail_message_id,
  error; unique (journey_id, kind, recipient) for dedup.

**Contacts setup**
- `GET /api/google/contacts?q=` searches the person's Google Contacts (People API) for the picker.
- `POST/GET/PATCH/DELETE /api/contacts` manage trusted contacts and their priority.

**Escalation engine** (new `app/escalation.py`)
- `JourneyService` notifies the engine on every risk update, check-in creation, help request and
  no-signal alert. The engine decides tier changes and sends emails through a `Mailer` interface
  (Gmail implementation; fake in tests).
- The existing background loop also calls `engine.tick(now)` every `WATCHDOG_INTERVAL_S`, which
  advances sequential escalations whose `next_step_at` has passed and escalates unanswered medium
  check-ins. State is read from / written to Supabase, so a restart resumes.
- `GET /api/escalations/{id}/ack?token=…` → marks acknowledged, publishes an SSE event, returns a
  simple "Thanks, the others won't be emailed" page.
- New `RiskConfig.critical_min = 90`. New env: `CHECKIN_REPLY_TIMEOUT_S=180`,
  `ESCALATION_STEP_S=300`.
- If Gmail send fails, the failure is logged in `notifications_sent` and the engine moves on to the
  next contact rather than stalling.

**Config (`.env`)**: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
`GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/google/callback`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `TOKEN_ENCRYPTION_KEY`, `PUBLIC_BASE_URL=http://localhost:8000`.
Without them, Google/Supabase features report "not configured" and everything else works as today.

**Testing**
- Fakes for the store (in-memory implementation of the same repository interface), Gmail and People.
- pytest covers: tier transitions, unanswered check-in → sequential, 5-min step to next contact,
  jump to "all" at 90+, help/no-signal → all, ack stops further emails, dedup, restart resume,
  Gmail failure skips ahead, offline mode unchanged. Existing 66 tests keep passing.
- One manual end-to-end run with the real account: connect, add a contact, replay the "lost"
  scenario with short delays, receive emails, click "I'm on it".

**Escalation lifecycle** (calls marked *[Claude's call]* are proposals the user can override)
- *[Claude's call]* Journeys stay in memory. Each escalation row stores a **snapshot** (person name,
  start, destination, last known location + time, latest risk reasons) so emails and `tick()` work
  after a restart even though the journey is gone; resumed escalations keep running on the snapshot.
- *[Claude's call]* One escalation per **episode**, not per journey: a new one opens only when no open
  escalation exists for that journey. Dedup key is (escalation_id, kind, recipient), so a second
  episode later in the same journey emails again.
- *[Claude's call]* Escalations link to the existing alerts: acknowledging the alert on the dashboard
  closes the escalation and vice versa. One "I'm on it" token **per recipient** (stored in
  `notifications_sent.ack_token_hash`) so `acknowledged_by` records who clicked.
- *[Claude's call]* Closed automatically when the journey is completed/cancelled (arrived home) and,
  for a no-signal escalation, when GPS comes back (mirrors the existing `_resolve_no_signal`).
- *[Claude's call]* Any check-in answer (including "Show me the way") within 3 min cancels the
  unanswered-check-in timer; a help request instead goes straight to "all".
- **[User to decide]** After the last contact gets no "I'm on it".
- **[User to decide]** Whether "I'm okay" from the person, or risk falling back to low, stops an
  escalation that has already emailed family.

## Left to the builder

- Exact email wording and HTML/plain-text layout (calm, short, includes last known location as a
  Google Maps link, journey start/destination, and the disclaimer).
- Module layout beyond `escalation.py`, repository interface shape, and the SQL migration file.
- Minimal setup page UI (connect button, contact picker, priority ordering).
