# Add Calendar Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A caregiver creates a timed event in the connected Google Calendar from an "Add to calendar" card on `/manage`.

**Architecture:** A new `calendar.events` scope plus a `POST /api/google/calendar/events` route in `accounts_api.py`, backed by a `CalendarWriter` in `google_services.py` that calls an injectable `events().insert` helper (same pattern as `CalendarReader` / `calendar_list`). The client adds `createCalendarEvent()` in `journeyApi.js` and an `AddToCalendar` card in `CareScreens.jsx`, refreshing the existing calendar state after a save.

**Tech Stack:** FastAPI, google-api-python-client, pytest; React 19 (no Node on this Mac: client checked in the browser harness).

**Spec:** `docs/superpowers/specs/2026-11-22-add-calendar-events-design.md`

## Global Constraints

- New scope: `https://www.googleapis.com/auth/calendar.events`, added next to `calendar.readonly` (not replacing it).
- Body: `title` 1–100 chars, `start` ISO 8601 date-time with offset, `duration_min` 15–480 (default 60), `note` optional ≤ 500 chars.
- Response 201: `{title, start, end, link}`. Errors: 401 `session_required`, 403 `calendar_write_not_allowed`, 422 bad input, 502 Google failure.
- Event goes to `settings.google_calendar_id` or `"primary"`. No attendees ever.
- Length choices in the UI: 30 min, 1 hour (default), 2 hours.
- Logs record only error types, never titles, notes or tokens (existing rule in `google_services.py`).

## Review Focus

- `start` without a UTC offset (e.g. `2026-11-25T10:00`) → 422, never a silently-UTC event.
- Title that is only spaces → 422.
- Account connected before this change (no `calendar.events` scope) → 403 with a reconnect message; the card shows "Reconnect Google to allow adding events".
- After a successful create, `GET /api/google/calendar/next` returns fresh data (cache cleared), not the 30-second-old event.
- Google raising during insert → 502 with a plain message, and the error text isn't logged.

---

### Task 1: Backend create-event route

**Files:**
- Modify: `backend/app/google_auth.py:37-42` (SCOPES)
- Modify: `backend/app/google_services.py` (writer + helper + `CALENDAR_WRITE_SCOPE`; `CalendarReader.forget(person_key)`)
- Modify: `backend/app/accounts_api.py` (route), `backend/app/main.py` (wire `calendar_inserter`)
- Test: `backend/tests/test_google_services.py`

**Interfaces:**
- Produces: `CalendarInserter = Callable[[Any, str, dict], dict]` — (credentials, calendar ID, event body) → Google event (`htmlLink`, `start`, `end`, `summary`).
- Produces: `calendar_insert(credentials, calendar_id, body) -> dict` (real Google call, `sendUpdates="none"`).
- Produces: `CalendarWriter(settings, google, inserter=None).create(session, title, start: datetime, duration_min, note) -> dict` returning `{title, start, end, link}`.
- Produces: `create_app(..., calendar_inserter: CalendarInserter | None = None)`.
- Produces: `POST /api/google/calendar/events` with body model `CalendarEventCreate`.

- [ ] **Step 1: Write the failing tests** (FakeGoogle gets `insert_event` recording calls; `build` passes `calendar_inserter=fake.insert_event`; exchange code `"no-calendar-write"` returns SCOPES without `calendar.events`)

```python
def test_caregiver_adds_a_calendar_event(tmp_path):
    client, fake, _ = build(tmp_path); connect(client)
    r = client.post("/api/google/calendar/events", json={"title": " Doctor appointment ", "start": "2099-03-02T10:00:00-05:00", "duration_min": 60, "note": "Bring the card"})
    assert r.status_code == 201
    assert r.json() == {"title": "Doctor appointment", "start": "2099-03-02T10:00:00-05:00", "end": "2099-03-02T11:00:00-05:00", "link": "https://calendar.google.com/event?eid=1"}
    cal_id, body = fake.inserted[0]
    assert cal_id == "test-calendar" and body["summary"] == "Doctor appointment" and body["description"] == "Bring the card"
    assert "attendees" not in body

def test_new_event_shows_in_next_event_right_away(tmp_path): ...  # read /calendar/next, insert, events list now has the new event, /next returns it without waiting

@pytest.mark.parametrize("bad", [{"title": "   "}, {"start": "2099-03-02T10:00:00"}, {"duration_min": 5}, {"duration_min": 600}, {"note": "x" * 501}, {"title": "x" * 101}])
def test_bad_event_input_is_rejected(tmp_path, bad): ...  # 422, no insert call

def test_old_connection_without_calendar_write_must_reconnect(tmp_path): ...  # connect(code="no-calendar-write") → 403 calendar_write_not_allowed

def test_google_failure_returns_502_without_logging_details(tmp_path, caplog): ...  # insert raises RuntimeError("secret") → 502, "secret" not in caplog.text
```
Also add `("post", "/api/google/calendar/events", {...valid body...})` to the `test_private_routes_require_a_session` list.

- [ ] **Step 2: Run them to see them fail**
Run: `.venv/bin/python -m pytest tests/test_google_services.py -q -k "calendar_event or next_event_right_away or bad_event or calendar_write or google_failure_returns or private_routes"`
Expected: new tests FAIL (404 / missing fixture attribute).

- [ ] **Step 3: Implement** the scope, `calendar_insert`, `CalendarWriter`, `CalendarReader.forget`, the route and wiring. `start` must be timezone-aware (reject naive with 422 via a pydantic validator); title is stripped before the length check; `end = start + duration`; the writer checks the account has `CALENDAR_WRITE_SCOPE` with `_has_scope`.

- [ ] **Step 4: Run the whole backend suite**
Run: `.venv/bin/python -m pytest -q` (from `backend/`, live tests skip without keys)
Expected: all pass.

- [ ] **Step 5: Commit** `git commit -m "Add a route to create Google Calendar events"`

### Task 2: Care dashboard "Add to calendar" card

**Files:**
- Modify: `client/src/data/journeyApi.js` (`createCalendarEvent`), `client/src/CareScreens.jsx` (`AddToCalendar`), `client/src/BackendDemo.jsx` (pass `onAddEvent`, refresh calendar after save), `client/src/app-ui.css` (small layout rules if needed)

**Interfaces:**
- Consumes: `POST /api/google/calendar/events` from Task 1.
- Produces: `createCalendarEvent({title, start, durationMin, note}) -> Promise<{title, start, end, link}>`; errors carry `.status` and `.code` (from `error.code` in the API body).
- Produces: `readCalendarReminder()` result gains `canWrite: boolean` (status `scopes` include `calendar.events`).

- [ ] **Step 1: Implement** `AddToCalendar({ calendar, onAdd })` under the "Next on the patient's calendar" panel: fields What / Date / Time / Length (30 min, 1 hour, 2 hours) / Note; `start` built from the date + time inputs as a local time with the browser's offset (`+HH:MM`). States: not connected → hidden (the calendar panel already explains); connected without `canWrite` → "Reconnect Google to allow adding events" + Connect Google link (`/api/google/connect`); success → "Added: {title}, {eventTime} · Open in Google Calendar" (link, new tab) and the form clears; failure → the server's message.
- [ ] **Step 2: Verify in the browser harness** (`gi-run-client` on 5173 against the ui backend): card renders, the reconnect state shows for the old connection, no console errors.
- [ ] **Step 3: Commit** `git commit -m "Care dashboard: add events to Google Calendar"`

### Task 3: End-to-end check and push

- [ ] Reconnect Google in the browser pane (user approves the new permission).
- [ ] Add a test event from `/manage`; confirm the success line, the Google link, and that `/api/google/calendar/next` shows it if it's the soonest. Then delete the test event in Google Calendar only if the user wants it gone.
- [ ] `git push origin ui`.
