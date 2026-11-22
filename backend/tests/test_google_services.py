"""Connect Google, one help email, and one Calendar event, using fake Google services."""
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryStore
from app.google_auth import OAUTH_STATE_COOKIE, SCOPES, SESSION_COOKIE, GoogleAuth, TokenResult, _failure_code
from app.main import _RedactOAuthCallback, create_app
from tests.conftest import far_off_route, iso, make_journey, send

ACCOUNT = "patient.test@example.com"
CAREGIVER = "caregiver.test@example.com"
CLIENT_JSON = {"web": {
    "client_id": "test-client.apps.googleusercontent.com",
    "client_secret": "test-secret",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://localhost:8000/api/google/callback"],
}}


class FakeGoogle:
    def __init__(self):
        self.sent = []
        self.fail_send = False
        self.events = []
        self.fail_calendar = False
        self.calendar_calls = []

    def send(self, credentials, raw):
        self.sent.append(message_from_bytes(base64.urlsafe_b64decode(raw)))
        if self.fail_send:
            raise RuntimeError("secret provider detail")
        return f"gmail-{len(self.sent)}"

    def list_events(self, credentials, calendar_id, time_min):
        self.calendar_calls.append((calendar_id, time_min))
        if self.fail_calendar:
            raise RuntimeError("calendar down")
        return self.events


def build(tmp_path, fake=None, **over):
    fake = fake or FakeGoogle()
    path = tmp_path / "client.json"
    path.write_text(json.dumps(CLIENT_JSON))
    values = {
        "route_mode": "offline", "google_oauth_client_file": path,
        "token_encryption_key": Fernet.generate_key().decode(), "google_allowed_email": ACCOUNT,
        "help_email_to": CAREGIVER, "help_email_consent": True, "google_calendar_id": "test-calendar",
    }
    values.update(over)
    settings = Settings(**values)
    store = MemoryStore()

    def exchange(code, verifier):
        email = "someone.else@example.com" if code == "wrong-account" else ACCOUNT
        scopes = [s for s in SCOPES if "gmail" not in s] if code == "no-gmail" else SCOPES
        return TokenResult("refresh-secret", scopes, email)

    google = GoogleAuth(settings, store, exchange=exchange)
    app = create_app(settings, store=store, google=google, gmail_sender=fake.send, calendar_lister=fake.list_events)
    return TestClient(app, follow_redirects=False), fake, store


def connect(client, code="good"):
    response = client.get("/api/google/connect")
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    return client.get("/api/google/callback", params={"state": state, "code": code})


def help_request(client, journey_id):
    return client.post(f"/api/journeys/{journey_id}/checkin", json={"help_requested": True})


def help_emails(fake):
    return [m for m in fake.sent if m["Subject"] == "What's Next? help request"]


def alerts(client):
    return [a for a in client.get("/api/alerts").json() if a["type"] == "help_request"]


# ---------------------------------------------------------------- sessions and access
@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/contacts", None),
    ("post", "/api/contacts", {"name": "A", "email": "a@example.com", "priority": 1}),
    ("get", "/api/contacts/some-id", None),
    ("patch", "/api/contacts/some-id", {"name": "B"}),
    ("delete", "/api/contacts/some-id", None),
    ("put", "/api/contacts/order", {"ids": []}),
    ("post", "/api/google/disconnect", None),
    ("get", "/api/escalations", None),
    ("get", "/api/escalations/some-id", None),
    ("post", "/api/escalations/tick", None),
    ("post", "/api/reminders/email-now", None),
])
def test_private_routes_require_a_session(tmp_path, method, path, body):
    client, *_ = build(tmp_path)
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401 and response.json()["error"]["code"] == "session_required"


def test_another_browser_sees_no_account_or_calendar(tmp_path):
    client, fake, store = build(tmp_path)
    assert connect(client).status_code == 200
    fake.events = [{"summary": "Private event", "start": {"dateTime": "2099-01-01T10:00:00Z"}}]
    other = TestClient(client.app, follow_redirects=False)
    status = other.get("/api/google/status").json()
    assert status["connected"] is False and "google_email" not in status
    assert other.get("/api/google/calendar/next").json() == {"state": "not_connected"}
    assert fake.calendar_calls == []


def test_email_settings_require_a_session(tmp_path):
    client, *_ = build(tmp_path)
    assert "help_email_to" not in client.get("/api/google/status").json()
    assert connect(client).status_code == 200
    status = client.get("/api/google/status").json()
    assert status["help_email_to"] == CAREGIVER
    assert status["help_email_consent"] is True and status["help_email_ready"] is True
    other = TestClient(client.app, follow_redirects=False)
    assert "help_email_to" not in other.get("/api/google/status").json()


def test_email_settings_report_missing_consent(tmp_path):
    client, *_ = build(tmp_path, help_email_consent=False)
    assert connect(client).status_code == 200
    status = client.get("/api/google/status").json()
    assert status["help_email_consent"] is False and status["help_email_ready"] is False


def test_only_the_approved_google_account_can_connect(tmp_path):
    client, _, store = build(tmp_path)
    response = connect(client, "wrong-account")
    assert response.status_code == 403 and store.get_google_account() is None
    assert SESSION_COOKIE not in client.cookies


def test_connect_fails_closed_without_an_allowed_account(tmp_path):
    client, _, store = build(tmp_path, google_allowed_email=None)
    assert connect(client).status_code == 403 and store.get_google_account() is None


def test_callback_must_finish_in_the_starting_browser(tmp_path):
    client, _, store = build(tmp_path)
    state = parse_qs(urlparse(client.get("/api/google/connect").headers["location"]).query)["state"][0]
    other = TestClient(client.app, follow_redirects=False)
    assert other.get("/api/google/callback", params={"state": state, "code": "good"}).status_code == 400
    assert store.get_google_account() is None


def test_callback_error_is_escaped(tmp_path):
    client, *_ = build(tmp_path)
    response = client.get("/api/google/callback", params={"error": "<script>alert(1)</script>"})
    assert response.status_code == 400 and "<script>" not in response.text and "&lt;script&gt;" in response.text


def test_session_cookie_is_http_only_and_contains_no_token(tmp_path):
    client, *_ = build(tmp_path)
    response = connect(client)
    header = next(v for k, v in response.headers.multi_items() if k == "set-cookie" and v.startswith(SESSION_COOKIE))
    assert "HttpOnly" in header and "SameSite=lax" in header and "refresh-secret" not in header
    assert OAUTH_STATE_COOKIE not in client.cookies


def test_tampered_or_disconnected_session_stops_working(tmp_path, monkeypatch):
    client, *_ = build(tmp_path)
    connect(client)
    token = client.cookies[SESSION_COOKIE]
    other = TestClient(client.app, cookies={SESSION_COOKIE: token[:-3] + "abc"})
    assert other.get("/api/contacts").status_code == 401
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: None)
    assert client.post("/api/google/disconnect").status_code == 200
    stale = TestClient(client.app, cookies={SESSION_COOKIE: token})
    assert stale.get("/api/contacts").status_code == 401


def test_oauth_query_is_redacted_from_access_logs():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1", "GET", "/api/google/callback?code=secret&state=secret", "1.1", 200), None)
    assert _RedactOAuthCallback().filter(record) and "secret" not in record.getMessage()


def test_emailed_ack_token_is_redacted_from_access_logs():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1", "POST", "/api/escalations/ack?token=secret", "1.1", 200), None)
    assert _RedactOAuthCallback().filter(record) and "secret" not in record.getMessage()


def test_visit_reminders_stay_private_without_a_session(tmp_path):
    client, *_ = build(tmp_path)
    assert client.get("/api/reminders").json() == {
        "available": False, "problem": "Connect Google to continue.", "reminders": []}


def test_help_sends_one_generic_email_even_with_trusted_contacts(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    contact = {"name": "Family Member", "email": "family.test@example.com", "priority": 1}
    assert client.post("/api/contacts", json=contact).status_code == 201
    journey = make_journey(client)
    send(client, journey["id"], *far_off_route(0, -400), 0)
    assert [m["To"] for m in fake.sent] == [ACCOUNT]          # her check-in, through the same fake Gmail
    fake.sent.clear()
    for _ in range(2):
        assert help_request(client, journey["id"]).status_code == 200
    assert [m["To"] for m in fake.sent] == [CAREGIVER]
    assert fake.sent[0]["Subject"] == "What's Next? help request"


def test_unapproved_stored_account_sends_no_escalation_email(tmp_path):
    client, fake, store = build(tmp_path)
    connect(client)
    journey = make_journey(client)
    account = store.get_google_account()
    store.save_google_account({"google_email": "someone.else@example.com", "scopes": account["scopes"],
                               "refresh_token_enc": account["refresh_token_enc"]})
    send(client, journey["id"], *far_off_route(0, -400), 0)
    assert fake.sent == []


def test_open_demo_walk_without_session_sends_no_escalation_email(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    contact = {"name": "Family Member", "email": "family.test@example.com", "priority": 1}
    assert client.post("/api/contacts", json=contact).status_code == 201
    outsider = TestClient(client.app)
    journey = make_journey(outsider)
    assert send(outsider, journey["id"], *far_off_route(0, -400), 0)["checkin_created"]
    client.app.state.escalation.tick()
    assert fake.sent == [] and client.get("/api/escalations").json() == []


def signed_id_token(issued_in_s):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from google.auth import crypt, jwt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(crypt.RSASigner.from_string(private, "test-key"), {
        "iss": "https://accounts.google.com", "aud": CLIENT_JSON["web"]["client_id"], "sub": "1",
        "email": ACCOUNT, "email_verified": True, "iat": now + issued_in_s, "exp": now + 3600})
    return token.decode(), public


@pytest.mark.parametrize("issued_in_s,accepted", [(3, True), (30, False)])
def test_id_token_allows_only_a_small_clock_difference(tmp_path, monkeypatch, issued_in_s, accepted):
    from types import SimpleNamespace

    from google.auth.exceptions import InvalidValue
    from google.oauth2 import id_token

    client, *_ = build(tmp_path)
    google = client.app.state.google
    token, public = signed_id_token(issued_in_s)
    monkeypatch.setattr(id_token, "_fetch_certs", lambda request, url: {"test-key": public})
    creds = SimpleNamespace(refresh_token="refresh", id_token=token, granted_scopes=SCOPES, scopes=SCOPES)
    monkeypatch.setattr(google, "_flow", lambda: SimpleNamespace(code_verifier=None, credentials=creds,
                                                                 fetch_token=lambda code: None))
    if accepted:
        assert google._google_exchange("code", "verifier").email == ACCOUNT
    else:
        with pytest.raises(InvalidValue) as failure:
            google._google_exchange("code", "verifier")
        assert _failure_code(failure.value) == "id_token_used_too_early"


def test_exchange_failure_code_hides_provider_text():
    assert _failure_code(RuntimeError("private token text")) == "unclassified"


# ---------------------------------------------------------------- one help email
def test_help_saves_alert_and_sends_one_generic_email(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    journey = make_journey(client)
    client.post(f"/api/journeys/{journey['id']}/location",
                json={"latitude": 45.5098, "longitude": -73.579, "timestamp": iso(2)})
    first = help_request(client, journey["id"]).json()
    second = help_request(client, journey["id"]).json()
    third = help_request(client, journey["id"]).json()
    assert first["alert"]["id"] == second["alert"]["id"] == third["alert"]["id"]
    assert len(help_emails(fake)) == 1 and len(alerts(client)) == 1
    assert alerts(client)[0]["email_status"] == "accepted"
    message = help_emails(fake)[0]
    assert message["To"] == CAREGIVER and message["Subject"] == "What's Next? help request"
    text = message.get_payload(decode=True).decode()
    for private in ("Margaret", "Tim Hortons", "Home", "45.", "-73.", "health", "Alzheimer", ACCOUNT):
        assert private not in text


def test_gmail_failure_keeps_alert_and_is_not_retried(tmp_path, caplog):
    fake = FakeGoogle()
    fake.fail_send = True
    client, fake, _ = build(tmp_path, fake)
    connect(client)
    journey = make_journey(client)
    assert help_request(client, journey["id"]).status_code == 200
    assert help_request(client, journey["id"]).status_code == 200
    assert len(fake.sent) == 1
    saved = alerts(client)
    assert len(saved) == 1 and saved[0]["priority"] == "critical" and saved[0]["email_status"] == "failed"
    assert "secret provider detail" not in caplog.text and CAREGIVER not in caplog.text


@pytest.mark.parametrize("over", [{"help_email_to": None}, {"help_email_consent": False}])
def test_no_email_without_recipient_and_consent(tmp_path, over):
    client, fake, _ = build(tmp_path, **over)
    connect(client)
    journey = make_journey(client)
    assert help_request(client, journey["id"]).status_code == 200
    assert fake.sent == [] and alerts(client)[0]["email_status"] == "not_sent"


def test_open_demo_help_without_session_sends_nothing(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    outsider = TestClient(client.app)
    journey = make_journey(outsider)
    assert help_request(outsider, journey["id"]).status_code == 200
    assert fake.sent == [] and alerts(outsider)[0]["email_status"] == "not_sent"


def test_no_email_without_gmail_permission(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client, "no-gmail")
    journey = make_journey(client)
    help_request(client, journey["id"])
    assert fake.sent == [] and alerts(client)[0]["email_status"] == "not_sent"


def test_i_need_help_with_open_checkin_uses_same_email_path(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    journey = make_journey(client)
    checkin = None
    for minute, lat in ((1, 45.5060), (3, 45.5098)):
        checkin = client.post(f"/api/journeys/{journey['id']}/location",
                              json={"latitude": lat, "longitude": -73.579, "timestamp": iso(minute)}).json()["checkin_created"] or checkin
    assert checkin
    response = client.post(f"/api/journeys/{journey['id']}/checkin",
                           json={"help_requested": True, "checkin_id": checkin["id"]})
    assert response.status_code == 200 and len(help_emails(fake)) == 1


# ---------------------------------------------------------------- calendar
def test_calendar_returns_only_title_and_time_of_next_event(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    now = datetime.now(timezone.utc)
    fake.events = [
        {"summary": "Already started", "start": {"dateTime": (now - timedelta(minutes=5)).isoformat()}},
        {"summary": "Lunch with family", "start": {"dateTime": (now + timedelta(hours=2)).isoformat()},
         "location": "Private address", "description": "Private notes"},
    ]
    result = client.get("/api/google/calendar/next").json()
    assert result["state"] == "ok" and set(result["event"]) == {"title", "start", "all_day"}
    assert result["event"]["title"] == "Lunch with family" and "Private" not in json.dumps(result)
    assert fake.calendar_calls[0][0] == "test-calendar"


def test_calendar_empty_unavailable_and_not_configured(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    fake.fail_calendar = True
    assert client.get("/api/google/calendar/next").json() == {"state": "unavailable"}
    fake.fail_calendar = False
    assert client.get("/api/google/calendar/next").json() == {"state": "empty"}
    unset, *_ = build(tmp_path, google_calendar_id=None)
    connect(unset)
    assert unset.get("/api/google/calendar/next").json() == {"state": "not_configured"}


# ---------------------------------------------------------------- preserved behavior
def test_maps_server_key_is_still_never_exposed(tmp_path):
    client, *_ = build(tmp_path, google_api_key="server", google_browser_key="server")
    assert client.get("/api/maps-config").json() == {"browser_key": None, "maps_enabled": False}
    separate, *_ = build(tmp_path, google_api_key="server", google_browser_key="browser")
    assert separate.get("/api/maps-config").json() == {"browser_key": "browser", "maps_enabled": True}


def test_messages_survive_alongside_help_and_stay_separate(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    assert client.post("/api/messages", json={"body": "I got home."}).status_code == 201
    assert fake.sent == [] and client.get("/api/alerts").json() == []
    assert client.get("/api/messages").json()[0]["body"] == "I got home."


def test_two_way_messages_keep_their_sender(tmp_path):
    client, *_ = build(tmp_path)
    old_style = client.post("/api/messages", json={"body": "From the patient."}).json()
    reply = client.post("/api/messages", json={"body": "From care.", "sender_role": "caregiver"}).json()
    assert old_style["sender_role"] == "patient" and reply["sender_role"] == "caregiver"
    assert [m["id"] for m in client.get("/api/messages").json()] == [reply["id"], old_style["id"]]
    assert client.post("/api/messages", json={"body": "No.", "sender_role": "admin"}).status_code == 422


def test_clear_demo_chat_keeps_walk_and_help_alert(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    journey = make_journey(client)
    assert help_request(client, journey["id"]).status_code == 200
    client.post("/api/messages", json={"body": "A chat message."})
    before = (client.get("/api/journeys").json(), client.get("/api/alerts").json(), len(fake.sent))
    assert client.post("/api/demo/messages/clear").json() == {"cleared": 1}
    assert client.get("/api/messages").json() == []
    assert (client.get("/api/journeys").json(), client.get("/api/alerts").json(), len(fake.sent)) == before


def test_typing_help_in_chat_is_only_a_message(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    make_journey(client)
    assert client.post("/api/messages", json={"body": "help"}).status_code == 201
    assert client.get("/api/alerts").json() == [] and fake.sent == []


def test_im_okay_sends_no_help_email(tmp_path):
    client, fake, _ = build(tmp_path)
    connect(client)
    journey = make_journey(client)
    response = None
    for minute, lat in ((1, 45.5060), (3, 45.5098)):
        response = client.post(f"/api/journeys/{journey['id']}/location",
                               json={"latitude": lat, "longitude": -73.579, "timestamp": iso(minute)}).json()
    assert response["checkin_created"]["options"] == ["I'm okay", "I need help"]
    answer = client.post(f"/api/journeys/{journey['id']}/checkin", json={"response": "I'm okay"}).json()
    assert answer["alert"]["type"] == "said_okay" and help_emails(fake) == []
