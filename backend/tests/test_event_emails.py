"""Calendar event emails, offline: every timed event -> one Gmail to Margaret 20 min before."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryStore
from app.event_emails import EventEmails
from app.main import create_app
from app.reminders import VisitReminders

from conftest import sign_in

ME = "margaret@gmail.com"
NOW = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)   # 3:00 PM Toronto
TORONTO = timezone(timedelta(hours=-5))


def at(minutes):
    return (NOW + timedelta(minutes=minutes)).astimezone(TORONTO).isoformat()


def ev(id, minutes, guests=(), title="Lunch", description=None, location=None, **extra):
    attendees = [{"email": ME, "self": True, "organizer": True}]
    attendees += [g if isinstance(g, dict) else {"email": g} for g in guests]
    return {"id": id, "status": "confirmed", "summary": title, "description": description,
            "location": location, "start": {"dateTime": at(minutes), "timeZone": "America/Toronto"},
            "end": {"dateTime": at(minutes + 60)}, "attendees": attendees, **extra}


class FakeMailer:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, to, subject, text, html=None):
        if self.fail:
            raise RuntimeError("Gmail down")
        self.sent.append({"to": to, "subject": subject, "text": text})
        return f"id-{len(self.sent)}"


class World:
    def __init__(self, **settings):
        self.now = NOW
        self.events = []
        self.settings = Settings(google_api_key=None, route_mode="offline", **settings)
        self.store = MemoryStore()
        self.store.save_google_account({"google_email": ME, "person_name": "Margaret",
                                        "refresh_token_enc": "x", "scopes": []})
        self.store.create_contact({"name": "Anna Smith", "email": "anna@gmail.com", "priority": 1,
                                   "relationship": "daughter"})
        self.mailer = FakeMailer()
        self.reminders = VisitReminders(self.store, self.settings, fetch=self.fetch, clock=self.clock)
        self.emails = EventEmails(self.store, self.mailer, self.reminders, self.settings, clock=self.clock)

    def clock(self):
        return self.now

    def fetch(self, a, b):
        return list(self.events), "America/Toronto"

    def tick(self, minutes_later=0):
        self.now += timedelta(minutes=minutes_later)
        self.reminders.clear_cache()
        return self.emails.tick()


@pytest.fixture
def w():
    return World()


def test_email_goes_to_margaret_20_min_before_with_everything(w):
    w.events = [ev("e1", 30, ["anna@gmail.com", {"email": "bob@x.com", "displayName": "Bob Brown"}],
                   title="Lunch together", description="<p>Bring the <b>photo album</b></p>",
                   location="Tim Hortons, Peel St")]
    assert w.tick() == 0 and w.mailer.sent == []              # 30 min away: too early
    assert w.tick(10) == 1                                    # 20 min away: send
    [m] = w.mailer.sent
    assert m["to"] == ME
    assert m["subject"] == "Reminder: Lunch together at 3:30 PM"
    t = m["text"]
    assert t.startswith("Hi Margaret,")
    assert "In 20 minutes, at 3:30 PM: Lunch together." in t
    assert "Who: Anna Smith (your daughter), Bob Brown" in t
    assert "Where: Tim Hortons, Peel St" in t
    assert "Details: Bring the photo album" in t


def test_sent_once_even_with_many_ticks(w):
    w.events = [ev("e1", 20)]
    for _ in range(5):
        w.tick(1)
    assert len(w.mailer.sent) == 1


def test_moved_event_is_sent_again(w):
    w.events = [ev("e1", 15)]
    w.tick()
    w.events = [ev("e1", 18)]                                 # moved by 3 minutes
    w.tick()
    assert len(w.mailer.sent) == 2 and "3:18 PM" in w.mailer.sent[1]["subject"]


def test_every_timed_event_counts_but_not_all_day_cancelled_or_started(w):
    w.events = [
        ev("alone", 10, title="Doctor"),                                   # no guests: still sent
        ev("cancelled", 10, status="cancelled"),
        ev("started", -5, title="Already on"),
        {"id": "allday", "status": "confirmed", "summary": "Stay",
         "start": {"date": "2026-11-21"}, "end": {"date": "2026-11-24"}},
    ]
    w.tick()
    assert [m["subject"] for m in w.mailer.sent] == ["Reminder: Doctor at 3:10 PM"]
    assert "Who:" not in w.mailer.sent[0]["text"] and "Details:" not in w.mailer.sent[0]["text"]


def test_declined_guests_and_margaret_herself_are_not_listed(w):
    w.events = [ev("e1", 10, [{"email": "anna@gmail.com", "responseStatus": "declined"},
                              {"email": "cara@gmail.com"}])]
    w.tick()
    t = w.mailer.sent[0]["text"]
    assert "Who: cara@gmail.com" in t and "Anna" not in t and ME not in t.split("Who:")[1].split("\n")[0]


def test_several_events_each_get_one_email_in_time_order(w):
    w.events = [ev("b", 15, title="Tea"), ev("a", 5, title="Pills")]
    w.tick()
    assert [m["subject"] for m in w.mailer.sent] == ["Reminder: Pills at 3:05 PM", "Reminder: Tea at 3:15 PM"]


def test_gmail_failure_is_recorded_and_not_resent(w):
    w.events = [ev("e1", 10)]
    w.mailer.fail = True
    assert w.tick() == 0
    notes = [n for n in w.store.notifications.values() if n["kind"].startswith("calendar_event:")]
    assert len(notes) == 1 and "Gmail down" in notes[0]["error"]
    w.mailer.fail = False
    w.tick(1)
    assert w.mailer.sent == []


def test_can_be_switched_off():
    w = World(calendar_emails=False)
    w.events = [ev("e1", 10)]
    assert w.tick() == 0 and w.mailer.sent == []


def test_not_connected_does_nothing(w):
    w.store.delete_google_account()
    w.events = [ev("e1", 10)]
    assert w.tick() == 0 and w.mailer.sent == []


def test_unapproved_account_is_not_read_or_emailed(w):
    w.mailer.ready = lambda: False
    w.reminders._fetch = lambda a, b: pytest.fail("the calendar must not be read")
    w.events = [ev("e1", 10)]
    assert w.tick() == 0 and w.mailer.sent == []


def test_lead_time_follows_the_setting():
    w = World(visit_reminder_lead_min=60)
    w.events = [ev("e1", 55)]
    w.tick()
    assert "In 55 minutes" in w.mailer.sent[0]["text"]


def test_manual_trigger_endpoint(w):
    client = sign_in(TestClient(create_app(w.settings, store=w.store, reminders=w.reminders, event_emails=w.emails)))
    w.events = [ev("e1", 10)]
    assert client.post("/api/reminders/email-now").json() == {"sent": 1}
    assert client.post("/api/reminders/email-now").json() == {"sent": 0}
