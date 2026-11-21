"""Gmail + Calendar integration, offline.

"Whenever a new Gmail is added as a trusted contact, it gets the alerts, and whatever is in the
calendar with that person shows up in the app." Every test here adds contacts through the real
API, then checks the emails (fake Gmail) and the reminders (fake Calendar). The Gmail and Calendar
plumbing itself (MIME message, API parameters) is checked with a fake googleapiclient service.
"""
import base64
import email
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryStore
from app.escalation import EscalationEngine
from app.geo import offset_point
from app.main import create_app
from app.mailer import GmailMailer
from app.reminders import VisitReminders

from conftest import far_off_route, make_journey, send

ME = "margaret@gmail.com"
NOW = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)   # 3:00 PM Toronto
TORONTO = timezone(timedelta(hours=-5))


# ---------------------------------------------------------------- fakes
class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, text, html=None):
        self.sent.append({"to": to, "subject": subject, "text": text})
        return f"id-{len(self.sent)}"

    def to(self):
        return [m["to"] for m in self.sent]


class FakeCalendar:
    def __init__(self):
        self.events = []
        self.calls = 0

    def fetch(self, time_min, time_max):
        self.calls += 1
        return list(self.events), "America/Toronto"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def at(minutes):
    return (NOW + timedelta(minutes=minutes)).astimezone(TORONTO).isoformat()


def visit(id, minutes, *guests, title="Visit", description=None, tz="America/Toronto", **extra):
    start = {"dateTime": at(minutes)}
    if tz:
        start["timeZone"] = tz
    return {"id": id, "status": "confirmed", "summary": title, "description": description,
            "start": start, "end": {"dateTime": at(minutes + 60)},
            "attendees": [{"email": ME, "self": True}] + [{"email": g} for g in guests], **extra}


@pytest.fixture
def app_env():
    settings = Settings(google_api_key=None, route_mode="offline",
                        checkin_reply_timeout_s=180, escalation_step_s=300)
    store = MemoryStore()
    store.save_google_account({"google_email": ME, "refresh_token_enc": "x", "scopes": []})
    mailer, cal, clock = FakeMailer(), FakeCalendar(), Clock()
    engine = EscalationEngine(store, mailer, settings, clock=clock)
    rem = VisitReminders(store, settings, fetch=cal.fetch, clock=clock)
    client = TestClient(create_app(settings, store=store, escalation=engine, reminders=rem),
                        follow_redirects=False)
    return client, mailer, cal, clock, engine, rem


def add(client, name, email, priority, relationship="family", **kw):
    r = client.post("/api/contacts", json={"name": name, "email": email, "priority": priority,
                                           "relationship": relationship, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def get_lost(client):
    """A walk that reaches high risk (contact #1 is emailed)."""
    j = make_journey(client)
    res = None
    for m in range(0, 11):
        res = send(client, j["id"], *offset_point(*far_off_route(0, -400), 0, -40 * m), m)
    assert res["risk"]["level"] == "high"
    return j


def get_critical(client):
    j = make_journey(client)
    res = None
    for m in range(0, 41):
        res = send(client, j["id"], *offset_point(*far_off_route(0, -400), 0, -40 * m), m)
    assert res["risk"]["score"] >= 90
    return j


def reminders(client):
    body = client.get("/api/reminders").json()
    assert body["available"], body
    return body["reminders"]


# ================================================================ Gmail: new contacts get alerts
def test_new_gmail_contact_is_emailed_first(app_env):
    client, mailer, *_ = app_env
    add(client, "Anna", "anna.new@gmail.com", 1)
    get_lost(client)
    assert mailer.to()[-1] == "anna.new@gmail.com"


def test_every_added_contact_is_reached_in_priority_order(app_env):
    client, mailer, cal, clock, engine, _ = app_env
    emails = [f"person{i}@gmail.com" for i in range(1, 6)]
    for i, e in enumerate(emails, 1):
        add(client, f"Person {i}", e, i)
    get_lost(client)
    for _ in emails:
        clock.now += timedelta(seconds=300)
        engine.tick()
    family = [t for t in mailer.to() if t != ME]
    assert family == emails                                   # all five, once each, in order


def test_contact_added_during_an_alert_is_still_reached(app_env):
    client, mailer, cal, clock, engine, _ = app_env
    add(client, "Anna", "anna@gmail.com", 1)
    get_lost(client)
    add(client, "Late Larry", "larry@gmail.com", 2)          # added after the alert started
    clock.now += timedelta(seconds=300)
    engine.tick()
    assert mailer.to()[-1] == "larry@gmail.com"


def test_reordering_changes_who_is_emailed_first(app_env):
    client, mailer, *_ = app_env
    a = add(client, "Anna", "anna@gmail.com", 1)
    b = add(client, "Ben", "ben@gmail.com", 2)
    client.put("/api/contacts/order", json={"ids": [b["id"], a["id"]]})
    get_lost(client)
    assert mailer.to()[-1] == "ben@gmail.com"


def test_changed_email_address_is_used(app_env):
    client, mailer, *_ = app_env
    a = add(client, "Anna", "old.anna@gmail.com", 1)
    client.patch(f"/api/contacts/{a['id']}", json={"email": "new.anna@gmail.com"})
    get_lost(client)
    assert "new.anna@gmail.com" in mailer.to() and "old.anna@gmail.com" not in mailer.to()


def test_deleted_contact_is_never_emailed(app_env):
    client, mailer, cal, clock, engine, _ = app_env
    a = add(client, "Anna", "anna@gmail.com", 1)
    add(client, "Ben", "ben@gmail.com", 2)
    client.delete(f"/api/contacts/{a['id']}")
    get_critical(client)
    assert "anna@gmail.com" not in mailer.to() and "ben@gmail.com" in mailer.to()


def test_critical_reaches_every_contact_including_new_ones(app_env):
    client, mailer, *_ = app_env
    for i in range(1, 4):
        add(client, f"P{i}", f"p{i}@gmail.com", i)
    add(client, "Newest", "newest@gmail.com", 9)
    get_critical(client)
    assert {"p1@gmail.com", "p2@gmail.com", "p3@gmail.com", "newest@gmail.com"} <= set(mailer.to())


def test_each_contact_gets_a_working_im_on_it_link(app_env):
    client, mailer, *_ = app_env
    for i in range(1, 4):
        add(client, f"P{i}", f"p{i}@gmail.com", i)
    get_critical(client)
    links = {m["to"]: m["text"].split("/api/escalations/ack?token=")[1].split()[0]
             for m in mailer.sent if "ack?token=" in m["text"]}
    assert len(set(links.values())) == 3                     # one token per person
    r = client.post("/api/escalations/ack", params={"token": links["p3@gmail.com"]})
    assert r.status_code == 200 and "P3" in r.text


def test_no_contacts_yet_means_only_the_person_is_emailed(app_env):
    client, mailer, *_ = app_env
    get_lost(client)
    assert mailer.to() == [ME]                               # her own check-in email, nothing else


# ================================================================ Gmail plumbing
class FakeGmailService:
    def __init__(self):
        self.bodies = []

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        assert userId == "me"
        self.bodies.append(body)
        return self

    def execute(self):
        return {"id": "gmail-123"}


class FakeGoogle:
    def __init__(self, store):
        self.store = store
        self.configured = True
        self.problem = None

    def credentials(self):
        return "creds"


def test_gmail_mailer_builds_a_real_email(monkeypatch):
    store = MemoryStore()
    store.save_google_account({"google_email": ME, "refresh_token_enc": "x", "scopes": []})
    svc, built = FakeGmailService(), []
    import googleapiclient.discovery as disc
    monkeypatch.setattr(disc, "build", lambda name, ver, credentials, cache_discovery: built.append(
        (name, ver, credentials)) or svc)

    msg_id = GmailMailer(FakeGoogle(store)).send("anna@gmail.com", "Margaret may need help",
                                                 "Hello Anna — café ☕", "<p>Hello</p>")
    assert msg_id == "gmail-123" and built == [("gmail", "v1", "creds")]
    raw = base64.urlsafe_b64decode(svc.bodies[0]["raw"])
    m = email.message_from_bytes(raw)
    assert m["To"] == "anna@gmail.com" and m["From"] == ME and m["Subject"] == "Margaret may need help"
    parts = {p.get_content_type(): p.get_payload(decode=True).decode() for p in m.walk()
             if not p.is_multipart()}
    assert "café ☕" in parts["text/plain"] and "<p>Hello</p>" in parts["text/html"]


def test_gmail_failure_is_recorded_not_crashing_the_walk(app_env):
    client, mailer, *_ = app_env
    add(client, "Anna", "anna@gmail.com", 1)
    mailer.send = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota exceeded"))
    j = get_lost(client)                                     # GPS endpoint still 200 throughout
    esc = client.get("/api/escalations", params={"journey_id": j["id"]}).json()[0]
    notes = client.get(f"/api/escalations/{esc['id']}").json()["notifications"]
    assert notes and all("quota exceeded" in n["error"] for n in notes)


# ================================================================ Calendar: events become reminders
def test_event_with_a_new_contact_shows_up_immediately(app_env):
    client, mailer, cal, *_ = app_env
    cal.events = [visit("e1", 10, "anna@gmail.com", title="Tea")]
    assert reminders(client) == []                          # Anna isn't a contact yet
    add(client, "Anna", "anna@gmail.com", 1, relationship="daughter")
    [r] = reminders(client)                                  # no 60 s wait: contacts aren't cached
    assert r["visitor"]["name"] == "Anna" and r["show_now"] and r["title"] == "Tea"


def test_removed_contact_disappears_from_reminders(app_env):
    client, mailer, cal, *_ = app_env
    a = add(client, "Anna", "anna@gmail.com", 1)
    cal.events = [visit("e1", 10, "anna@gmail.com")]
    assert len(reminders(client)) == 1
    client.delete(f"/api/contacts/{a['id']}")
    assert reminders(client) == []


def test_guest_email_case_doesnt_matter(app_env):
    client, mailer, cal, *_ = app_env
    add(client, "Anna", "Anna.Smith@Gmail.com", 1)
    cal.events = [visit("e1", 10, "anna.smith@gmail.com")]
    assert len(reminders(client)) == 1


def test_contact_photo_and_relationship_come_through(app_env):
    client, mailer, cal, *_ = app_env
    add(client, "Anna Smith", "anna@gmail.com", 1, relationship="granddaughter",
        photo_url="https://lh3.googleusercontent.com/a/photo", source="google")
    cal.events = [visit("e1", 10, "anna@gmail.com")]
    v = reminders(client)[0]["visitor"]
    assert v == {"name": "Anna Smith", "relationship": "granddaughter",
                 "photo_url": "https://lh3.googleusercontent.com/a/photo", "email": "anna@gmail.com"}


def test_moved_event_updates_after_the_cache_expires(app_env):
    client, mailer, cal, clock, engine, rem = app_env
    add(client, "Anna", "anna@gmail.com", 1)
    cal.events = [visit("e1", 10, "anna@gmail.com")]
    assert reminders(client)[0]["arrival_text"] == "3:10 PM"
    cal.events = [visit("e1", 50, "anna@gmail.com")]        # family moved it later
    assert reminders(client)[0]["arrival_text"] == "3:10 PM"  # still cached (≤ 60 s old)
    rem.clear_cache()
    r = reminders(client)[0]
    assert r["arrival_text"] == "3:50 PM" and r["show_now"] is False


def test_recurring_visit_instances_each_show(app_env):
    client, mailer, cal, *_ = app_env
    add(client, "Anna", "anna@gmail.com", 1)
    cal.events = [visit("weekly_20261121", 10, "anna@gmail.com", recurringEventId="weekly"),
                  visit("weekly_20261122", 10 + 24 * 60 - 1, "anna@gmail.com", recurringEventId="weekly")]
    rows = reminders(client)
    assert [r["event_id"] for r in rows] == ["weekly_20261121", "weekly_20261122"]
    assert [r["show_now"] for r in rows] == [True, False]


def test_times_in_utc_or_without_timezone_are_shown_in_toronto_time(app_env):
    client, mailer, cal, *_ = app_env
    add(client, "Anna", "anna@gmail.com", 1)
    utc_start = (NOW + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    e = visit("utc", 10, "anna@gmail.com", tz=None)
    e["start"] = {"dateTime": utc_start}                      # no timeZone: use the calendar's
    cal.events = [e]
    assert reminders(client)[0]["arrival_text"] == "3:10 PM"


def test_three_visitors_and_no_relationship_read_naturally(app_env):
    client, mailer, cal, *_ = app_env
    add(client, "Anna", "anna@gmail.com", 1, relationship="daughter")
    add(client, "Ben", "ben@gmail.com", 2, relationship=None)
    add(client, "Cara", "cara@gmail.com", 3, relationship="nurse")
    cal.events = [visit("e1", 10, "cara@gmail.com", "ben@gmail.com", "anna@gmail.com", title="Birthday")]
    r = reminders(client)[0]
    assert r["visitor"]["name"] == "Anna" and [c["name"] for c in r["with"]] == ["Ben", "Cara"]
    assert r["read_aloud"] == ("Anna, your daughter, Ben, and Cara, your nurse, are coming to visit "
                               "at 3:10 PM. Birthday.")


def test_long_html_description_is_cleaned_and_shortened(app_env):
    client, mailer, cal, *_ = app_env
    add(client, "Anna", "anna@gmail.com", 1)
    desc = "<p>Bring&nbsp;the <b>photo album</b> &amp; soup.</p><br>" + "More details. " * 40
    cal.events = [visit("e1", 10, "anna@gmail.com", title="Lunch", description=desc)]
    r = reminders(client)[0]
    assert r["reason"].startswith("Lunch — Bring the photo album & soup.")
    assert len(r["reason"]) <= 200 and r["reason"].endswith("…") and "<" not in r["reason"]


def test_event_she_organised_with_no_contact_guests_is_not_a_visit(app_env):
    client, mailer, cal, *_ = app_env
    add(client, "Anna", "anna@gmail.com", 1)
    cal.events = [visit("doctor", 10, "clinic@hospital.org", title="Doctor"),
                  visit("self", 10, ME, title="Me again")]
    assert reminders(client) == []


def test_calendar_fetch_asks_google_for_the_right_things(monkeypatch):
    seen = {}

    class Events:
        def list(self, **kw):
            seen.update(kw)
            return self

        def execute(self):
            return {"items": [], "timeZone": "America/Toronto"}

    class Svc:
        def events(self):
            return Events()

    import googleapiclient.discovery as disc
    monkeypatch.setattr(disc, "build", lambda *a, **k: Svc())
    store = MemoryStore()
    store.save_google_account({"google_email": ME, "refresh_token_enc": "x", "scopes": []})
    rem = VisitReminders(store, Settings(), google=FakeGoogle(store), clock=lambda: NOW)
    assert rem.list() == {"available": True, "problem": None, "reminders": []}
    assert seen["calendarId"] == "primary" and seen["singleEvents"] is True
    assert seen["orderBy"] == "startTime"
    t0, t1 = datetime.fromisoformat(seen["timeMin"]), datetime.fromisoformat(seen["timeMax"])
    assert t0 == NOW - timedelta(minutes=30) and t1 == NOW + timedelta(hours=24)


def test_calendar_and_gmail_together_for_the_same_new_contact(app_env):
    """One new Gmail address: it shows up as the visitor AND receives the alert."""
    client, mailer, cal, *_ = app_env
    add(client, "Dan", "dan.new@gmail.com", 1, relationship="neighbour")
    cal.events = [visit("e1", 15, "dan.new@gmail.com", title="Walk to the park")]
    assert reminders(client)[0]["visitor"]["relationship"] == "neighbour"
    get_lost(client)
    assert mailer.to()[-1] == "dan.new@gmail.com"
