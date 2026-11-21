"""Email escalation, offline: in-memory store, fake Gmail, fake wall clock.

Rules (decided by the user, 2026-11-21):
- medium (30-59): email the person "are you okay?"; no answer for 3 min -> sequential
- high (60-89): email contact #1; no "I'm on it" within 5 min -> #2 -> #3 ... then stop
- 90-100 or the help button: email every contact at once
- "I'm okay" after family was emailed: send them an "all good" update and close
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryStore
from app.escalation import EscalationEngine
from app.geo import offset_point
from app.main import create_app

from conftest import HOME, far_off_route, make_journey, send

ME = "margaret@example.com"


class FakeMailer:
    def __init__(self):
        self.sent: list[dict] = []
        self.fail_for: set[str] = set()

    def send(self, to, subject, text, html=None):
        if to in self.fail_for:
            raise RuntimeError("Gmail said no")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})
        return f"msg-{len(self.sent)}"

    def to(self):
        return [m["to"] for m in self.sent]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def env():
    settings = Settings(google_api_key=None, route_mode="offline",
                        checkin_reply_timeout_s=180, escalation_step_s=300)
    store = MemoryStore()
    store.save_google_account({"google_email": ME, "refresh_token_enc": "x", "scopes": []})
    for i, name in enumerate(["anna", "ben", "cara"], start=1):
        store.create_contact({"name": name.title(), "email": f"{name}@example.com", "priority": i,
                              "relationship": "family"})
    mailer, clock = FakeMailer(), Clock()
    engine = EscalationEngine(store, mailer, settings, clock=clock)
    client = TestClient(create_app(settings, store=store, escalation=engine), follow_redirects=False)
    return client, store, mailer, clock, engine


def walk_west(client, jid, start_min, end_min, west_m=400):
    """Keep walking west, far off the route (never 'standing still')."""
    res = None
    for m in range(start_min, end_min + 1):
        res = send(client, jid, *offset_point(*far_off_route(0, -west_m), 0, -40 * m), m)
    return res


def token_from(mail):
    url = re.search(r"https?://\S+/api/escalations/ack\?token=\S+", mail["text"]).group(0)
    return parse_qs(urlparse(url).query)["token"][0]


# ---------------------------------------------------------------- medium
def test_medium_emails_the_person_once(env):
    client, store, mailer, *_ = env
    j = make_journey(client)
    res = send(client, j["id"], *far_off_route(0, -400), 0)
    assert res["risk"]["level"] == "medium" and res["checkin_created"]
    assert mailer.to() == [ME]
    assert "are you okay" in mailer.sent[0]["text"].lower()
    send(client, j["id"], *far_off_route(0, -440), 1)        # still medium: no second email
    assert mailer.to() == [ME]


def test_unanswered_checkin_for_3_min_emails_contact_1(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    send(client, j["id"], *far_off_route(0, -400), 0)
    clock.advance(170)
    engine.tick()
    assert mailer.to() == [ME]
    clock.advance(20)
    engine.tick()
    assert mailer.to() == [ME, "anna@example.com"]


def test_answering_the_checkin_stops_the_3_min_timer(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    send(client, j["id"], *far_off_route(0, -400), 0)
    client.post(f"/api/journeys/{j['id']}/checkin", json={"response": "I'm okay"})
    clock.advance(600)
    engine.tick()
    assert mailer.to() == [ME]           # family never emailed, so no "all good" update either


# ---------------------------------------------------------------- high: one at a time
def test_high_emails_contacts_one_by_one_then_stops(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    res = walk_west(client, j["id"], 0, 10)
    assert res["risk"]["level"] == "high"
    assert mailer.to() == [ME, "anna@example.com"]
    walk_west(client, j["id"], 11, 12)                       # more high updates: no spam
    assert mailer.to() == [ME, "anna@example.com"]

    for expected in (["ben@example.com"], ["cara@example.com"], []):
        before = len(mailer.sent)
        clock.advance(299)
        engine.tick()
        assert len(mailer.sent) == before                    # not yet 5 min
        clock.advance(1)
        engine.tick()
        assert mailer.to()[before:] == expected              # after the last one: nothing more

    clock.advance(3600)
    engine.tick()
    assert mailer.to() == [ME, "anna@example.com", "ben@example.com", "cara@example.com"]


def test_family_email_has_where_and_an_ack_link(env):
    client, store, mailer, *_ = env
    j = make_journey(client)
    walk_west(client, j["id"], 0, 10)
    mail = mailer.sent[-1]
    assert "Margaret" in mail["subject"]
    assert "Tim Hortons" in mail["text"] and "google.com/maps" in mail["text"]
    assert "Not medically validated" in mail["text"]
    assert token_from(mail)


def test_im_on_it_stops_everyone(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    walk_west(client, j["id"], 0, 10)
    token = token_from(mailer.sent[-1])

    page = client.get("/api/escalations/ack", params={"token": token})
    assert page.status_code == 200 and "<form" in page.text   # a GET alone (link scanners) changes nothing
    assert store.list_escalations(status="open")

    r = client.post("/api/escalations/ack", params={"token": token})
    assert r.status_code == 200 and "Anna" in r.text
    esc = store.list_escalations()[0]
    assert esc["status"] == "acknowledged"
    assert esc["acknowledged_by"] == store.list_contacts()[0]["id"]
    assert all(a["acknowledged"] for a in client.get("/api/alerts").json() if a["type"] == "risk")

    clock.advance(3600)
    engine.tick()
    assert mailer.to() == [ME, "anna@example.com"]
    assert client.post("/api/escalations/ack", params={"token": token}).status_code == 200  # idempotent
    assert client.post("/api/escalations/ack", params={"token": "forged"}).status_code == 404


def test_dashboard_acknowledge_also_stops_emails(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    walk_west(client, j["id"], 0, 10)
    alert = client.get("/api/alerts").json()[0]
    client.post(f"/api/alerts/{alert['id']}/acknowledge")
    clock.advance(3600)
    engine.tick()
    assert mailer.to() == [ME, "anna@example.com"]


def test_gmail_failure_moves_on_to_next_contact(env):
    client, store, mailer, *_ = env
    mailer.fail_for.add("anna@example.com")
    j = make_journey(client)
    walk_west(client, j["id"], 0, 10)
    assert mailer.to() == [ME, "ben@example.com"]
    esc = store.list_escalations()[0]
    errors = [n for n in store.list_notifications(esc["id"]) if n["error"]]
    assert errors and errors[0]["recipient"] == "anna@example.com"


# ---------------------------------------------------------------- 90-100 / help: everyone
def test_critical_score_emails_everyone_at_once(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    res = walk_west(client, j["id"], 0, 40)
    assert res["risk"]["score"] >= 90
    family = [t for t in mailer.to() if t != ME]
    assert sorted(set(family)) == ["anna@example.com", "ben@example.com", "cara@example.com"]
    urgent = [m for m in mailer.sent if m["to"] == "cara@example.com"]
    assert urgent and "urgent" in urgent[-1]["subject"].lower()
    n = len(mailer.sent)
    walk_west(client, j["id"], 41, 43)                       # still 90+: no repeats
    clock.advance(3600)
    engine.tick()
    assert len(mailer.sent) == n


def test_help_button_emails_everyone(env):
    client, store, mailer, *_ = env
    j = make_journey(client)
    send(client, j["id"], *HOME, 0)
    client.post(f"/api/journeys/{j['id']}/checkin", json={"help_requested": True})
    assert sorted(mailer.to()) == ["anna@example.com", "ben@example.com", "cara@example.com"]
    client.post(f"/api/journeys/{j['id']}/checkin", json={"help_requested": True})
    assert len(mailer.sent) == 3


# ---------------------------------------------------------------- all good
def test_im_okay_after_family_emailed_sends_all_good_update(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    res = send(client, j["id"], *far_off_route(0, -400), 0)        # medium, check-in, email to her
    clock.advance(181)
    engine.tick()                                                   # unanswered -> Anna
    clock.advance(301)
    engine.tick()                                                   # -> Ben
    r = client.post(f"/api/journeys/{j['id']}/checkin",
                    json={"response": "I'm okay", "checkin_id": res["checkin_created"]["id"]})
    assert r.status_code == 200
    updates = mailer.sent[3:]
    assert [m["to"] for m in updates] == ["anna@example.com", "ben@example.com"]
    assert all("okay" in m["subject"].lower() for m in updates)
    assert store.list_escalations()[0]["status"] == "closed"
    clock.advance(3600)
    engine.tick()
    assert len(mailer.sent) == 5                                    # Cara never bothered


def test_arriving_closes_and_tells_family(env):
    client, store, mailer, *_ = env
    j = make_journey(client)
    walk_west(client, j["id"], 0, 10)
    client.post(f"/api/journeys/{j['id']}/complete")
    assert mailer.to()[-1] == "anna@example.com" and "arrived" in mailer.sent[-1]["subject"].lower()
    assert store.list_escalations()[0]["status"] == "closed"


def test_escalation_survives_restart(env):
    client, store, mailer, clock, engine = env
    j = make_journey(client)
    walk_west(client, j["id"], 0, 10)
    fresh = EscalationEngine(store, mailer, engine.settings, clock=clock)   # new process, same database
    clock.advance(300)
    fresh.tick()
    assert mailer.to()[-1] == "ben@example.com"
    assert "Tim Hortons" in mailer.sent[-1]["text"]                         # from the saved snapshot


def test_no_contacts_and_no_google_is_harmless(client):
    j = make_journey(client)
    res = walk_west(client, j["id"], 0, 40)
    assert res["risk"]["score"] >= 90                                       # offline app works as before
    r = client.post(f"/api/journeys/{j['id']}/checkin", json={"help_requested": True})
    assert r.status_code == 200


def test_escalations_api_lists_and_shows_emails(env):
    client, *_ = env
    j = make_journey(client)
    walk_west(client, j["id"], 0, 10)
    rows = client.get("/api/escalations").json()
    assert len(rows) == 1 and rows[0]["tier"] == "sequential" and rows[0]["journey_id"] == j["id"]
    detail = client.get(f"/api/escalations/{rows[0]['id']}").json()
    assert [n["recipient"] for n in detail["notifications"]] == [ME, "anna@example.com"]  # began as her check-in
    assert "ack_token_hash" not in detail["notifications"][0]
