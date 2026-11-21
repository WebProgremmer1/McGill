"""Runs against the REAL connected Google account (Gmail + Calendar). Skipped unless asked:

    RUN_GOOGLE_TESTS=1 python -m pytest tests/test_google_live.py -v

Optional settings (env vars):
    GOOGLE_TEST_RECIPIENT=someone@gmail.com   who receives the test alert emails
                                              (default: the connected account itself)
    GOOGLE_TEST_VISITOR=someone@gmail.com     a guest on a calendar event in the next 24 h;
                                              the test checks it becomes a visit reminder

Contacts and escalations live in a throwaway in-memory store, so the real Supabase contacts are
never read, emailed or changed. Each run sends about 4 real emails. Gmail can't be read back
(only gmail.send is granted), so "sent" means Gmail accepted it and returned a message id;
check the recipient's inbox (or the account's Sent folder) to see them.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryStore, create_store
from app.escalation import EscalationEngine
from app.geo import offset_point
from app.google_auth import SCOPES, GoogleAuth
from app.mailer import GmailMailer
from app.main import create_app
from app.reminders import VisitReminders

from conftest import far_off_route, make_journey, send

pytestmark = pytest.mark.skipif(os.getenv("RUN_GOOGLE_TESTS") != "1",
                                reason="set RUN_GOOGLE_TESTS=1 to use the real Google account")


@pytest.fixture(scope="module")
def live():
    settings = Settings.from_env()
    real_store = create_store(settings)
    acct = real_store.get_google_account()
    if not acct:
        pytest.skip("No Google account connected: open /api/google/connect first")
    store = MemoryStore()                                      # isolated contacts / escalations
    store.save_google_account({k: v for k, v in acct.items() if k not in ("id",)})
    google = GoogleAuth(settings, store)
    assert google.configured, google.problem
    me = acct["google_email"]
    return settings, store, google, me, os.getenv("GOOGLE_TEST_RECIPIENT") or me


# ---------------------------------------------------------------- connection
def test_connected_with_every_permission_and_token_works(live):
    _, _, google, _, _ = live
    s = google.status(check=True)
    assert s["connected"] and s["token_ok"], "Token refused: reconnect at /api/google/connect"
    assert s["missing_scopes"] == [], f"Reconnect and tick every box: {s['missing_scopes']}"
    assert set(SCOPES) <= set(s["scopes"])


# ---------------------------------------------------------------- Gmail
def test_gmail_accepts_a_plain_email(live):
    _, _, google, _, to = live
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    msg_id = GmailMailer(google).send(to, f"Walk Safety live test {stamp}",
                                      "Live test: Gmail sending works. You can delete this.")
    assert msg_id, "Gmail returned no message id"


def test_new_contact_receives_a_real_alert_then_an_arrived_update(live):
    settings, store, google, me, to = live
    for c in store.list_contacts():
        store.delete_contact(c["id"])
    engine = EscalationEngine(store, GmailMailer(google), settings)
    client = TestClient(create_app(Settings(route_mode="offline", public_base_url=settings.public_base_url),
                                   store=store, google=google, escalation=engine,
                                   reminders=VisitReminders(store, settings, google=google)))
    r = client.post("/api/contacts", json={"name": "Live Test", "email": to, "priority": 1,
                                           "relationship": "tester"})
    assert r.status_code == 201, r.text

    j = make_journey(client, user_name="Margaret (live test)")
    for m in range(0, 11):                                   # walks away until high risk
        res = send(client, j["id"], *offset_point(*far_off_route(0, -400), 0, -40 * m), m)
    assert res["risk"]["level"] == "high"

    esc = client.get("/api/escalations", params={"journey_id": j["id"]}).json()[0]
    notes = {n["kind"]: n for n in client.get(f"/api/escalations/{esc['id']}").json()["notifications"]}
    assert notes["sequential"]["recipient"] == to
    assert notes["sequential"]["error"] is None and notes["sequential"]["gmail_message_id"]
    if to != me:
        assert notes["person_checkin"]["error"] is None   # her own "are you okay?" email

    stored = [x for x in store.list_notifications(esc["id"]) if x["kind"] == "sequential"]
    assert stored[0]["ack_token_hash"]                       # the email carries an "I'm on it" link

    client.post(f"/api/journeys/{j['id']}/complete")         # sends the "arrived" update too
    notes = client.get(f"/api/escalations/{esc['id']}").json()["notifications"]
    arrived = [n for n in notes if n["kind"] == "arrived"]
    assert arrived and arrived[0]["error"] is None and arrived[0]["gmail_message_id"]


# ---------------------------------------------------------------- Calendar
def test_calendar_reads_and_every_real_event_is_handled(live):
    settings, store, google, me, _ = live
    rem = VisitReminders(store, settings, google=google)
    now = datetime.now(timezone.utc)
    events, tz = rem._google_fetch(now, now + timedelta(days=1))
    assert tz, "Calendar returned no time zone"

    # Make every guest on every real event a contact: each timed event with a guest must
    # then come back as a visit, and nothing may crash on real-world event shapes.
    for c in store.list_contacts():
        store.delete_contact(c["id"])
    guests = sorted({a["email"].lower() for e in events for a in e.get("attendees", [])
                     if a.get("email") and not a.get("self") and a["email"].lower() != me.lower()})
    for i, g in enumerate(guests, 1):
        store.create_contact({"name": g.split("@")[0], "email": g, "priority": i})
    body = rem.list()
    assert body["available"], body["problem"]
    expected = {e["id"] for e in events
                if e.get("status") != "cancelled" and (e.get("start") or {}).get("dateTime")
                and any(a.get("email", "").lower() in guests and a.get("responseStatus") != "declined"
                        for a in e.get("attendees", []))}
    assert {r["event_id"] for r in body["reminders"]} >= {
        i for i in expected if datetime.fromisoformat(
            next(e for e in events if e["id"] == i)["start"]["dateTime"].replace("Z", "+00:00")) > now}
    print(f"\n{len(events)} event(s) in the next 24 h, {len(body['reminders'])} visit reminder(s)")


@pytest.mark.skipif(not os.getenv("GOOGLE_TEST_VISITOR"),
                    reason="set GOOGLE_TEST_VISITOR and invite that email to an event in the next 24 h")
def test_invited_visitor_shows_up_as_a_reminder(live):
    settings, store, google, _, _ = live
    visitor = os.environ["GOOGLE_TEST_VISITOR"].strip().lower()
    for c in store.list_contacts():
        store.delete_contact(c["id"])
    store.create_contact({"name": "Test Visitor", "email": visitor, "priority": 1, "relationship": "friend"})
    body = VisitReminders(store, settings, google=google).list()
    assert body["available"], body["problem"]
    mine = [r for r in body["reminders"] if r["visitor"]["email"].lower() == visitor]
    assert mine, (f"No event in the next 24 h has {visitor} as a guest. Create one in Google "
                  "Calendar (with a start time, not all-day) and invite that address.")
    print(f"\nReminder: {mine[0]['read_aloud']} (shows on the phone: {mine[0]['show_now']})")
