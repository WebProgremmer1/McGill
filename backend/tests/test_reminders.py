"""Visit reminders from Google Calendar, offline (fake calendar, fake clock)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryStore
from app.main import create_app
from app.reminders import VisitReminders

from conftest import sign_in

NOW = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)      # 3:00 PM in Toronto
TZ = "America/Toronto"


def at(minutes):
    """An RFC 3339 time like Google returns, in Toronto time (UTC-5 in November)."""
    t = (NOW + timedelta(minutes=minutes)).astimezone(timezone(timedelta(hours=-5)))
    return t.isoformat()


def event(id, start_min, guests, title="Sunday lunch", description=None, length=60, **extra):
    return {"id": id, "status": "confirmed", "summary": title, "description": description,
            "start": {"dateTime": at(start_min), "timeZone": TZ},
            "end": {"dateTime": at(start_min + length), "timeZone": TZ},
            "attendees": [{"email": "margaret@example.com", "self": True, "organizer": True}]
                         + [{"email": e, "responseStatus": s} for e, s in guests], **extra}


class Fake:
    def __init__(self):
        self.now = NOW
        self.events = []
        self.calls = 0

    def clock(self):
        return self.now

    def fetch(self, time_min, time_max):
        self.calls += 1
        return [e for e in self.events], TZ


@pytest.fixture
def env():
    settings = Settings(google_api_key=None, route_mode="offline")
    store = MemoryStore()
    store.save_google_account({"google_email": "margaret@example.com", "refresh_token_enc": "x", "scopes": []})
    store.create_contact({"name": "Anna Smith", "email": "anna@example.com", "priority": 1,
                          "relationship": "daughter", "photo_url": "https://example.com/anna.jpg"})
    store.create_contact({"name": "Ben", "email": "Ben@Example.com", "priority": 2, "relationship": "son"})
    fake = Fake()
    rem = VisitReminders(store, settings, fetch=fake.fetch, clock=fake.clock)
    client = sign_in(TestClient(create_app(settings, store=store, reminders=rem)))
    return client, fake, rem


def get(client):
    r = client.get("/api/reminders")
    assert r.status_code == 200, r.text
    return r.json()


def test_visit_from_a_contact_guest(env):
    client, fake, _ = env
    fake.events = [event("e1", 15, [("anna@example.com", "accepted")],
                         title="Lunch together", description="<p>Bringing <b>soup</b></p>")]
    body = get(client)
    assert body["available"] is True
    [r] = body["reminders"]
    assert r["event_id"] == "e1" and r["show_now"] is True           # 15 min away: inside the 20 min window
    assert r["visitor"] == {"name": "Anna Smith", "relationship": "daughter",
                            "photo_url": "https://example.com/anna.jpg", "email": "anna@example.com"}
    assert r["arrival_text"] == "3:15 PM" and r["minutes_until"] == 15
    assert r["reason"] == "Lunch together — Bringing soup"
    assert r["read_aloud"] == ("Anna, your daughter, is coming to visit at 3:15 PM. "
                               "Lunch together. Bringing soup.")


def test_window_opens_20_min_before_and_closes_30_min_after(env):
    client, fake, rem = env
    fake.events = [event("e1", 45, [("anna@example.com", "accepted")])]
    assert get(client)["reminders"][0]["show_now"] is False          # 45 min away: listed, not shown
    for minutes, shown in ((20, False), (25, True), (60, True), (76, False)):
        fake.now = NOW + timedelta(minutes=minutes)
        rem.clear_cache()
        rows = get(client)["reminders"]
        assert (rows[0]["show_now"] if rows else False) is shown, minutes


def test_non_visits_are_ignored(env):
    client, fake, _ = env
    fake.events = [
        {"id": "allday", "status": "confirmed", "summary": "Stay at a residence",
         "start": {"date": "2026-11-19"}, "end": {"date": "2026-11-24"},
         "attendees": [{"email": "anna@example.com"}]},                        # all-day
        event("stranger", 10, [("plumber@example.com", "accepted")]),          # not a contact
        event("declined", 10, [("anna@example.com", "declined")]),             # Anna said no
        event("cancelled", 10, [("anna@example.com", "accepted")], status="cancelled"),
        event("alone", 10, []),                                                 # her own appointment
    ]
    assert get(client)["reminders"] == []


def test_two_contacts_main_visitor_is_first_priority(env):
    client, fake, _ = env
    fake.events = [event("e1", 10, [("ben@example.com", "needsAction"), ("anna@example.com", "accepted")],
                         title="Family visit")]
    [r] = get(client)["reminders"]
    assert r["visitor"]["name"] == "Anna Smith"
    assert [c["name"] for c in r["with"]] == ["Ben"]                   # email match ignores case
    assert r["read_aloud"].startswith("Anna, your daughter, and Ben, your son, are coming to visit at 3:10 PM.")


def test_sorted_and_cached(env):
    client, fake, _ = env
    fake.events = [event("late", 300, [("ben@example.com", "accepted")]),
                   event("soon", 10, [("anna@example.com", "accepted")])]
    assert [r["event_id"] for r in get(client)["reminders"]] == ["soon", "late"]
    get(client)
    assert fake.calls == 1                                             # second poll within 60 s: cached


def test_not_connected_is_quietly_unavailable(client):
    body = client.get("/api/reminders").json()
    assert body["available"] is False and body["reminders"] == [] and body["problem"]


def test_calendar_error_is_reported_not_raised(env):
    client, fake, _ = env

    def boom(*_):
        raise RuntimeError("calendar down")
    fake.fetch = boom
    env[2]._fetch = boom
    body = get(client)
    assert body["available"] is False and "calendar down" in body["problem"]
