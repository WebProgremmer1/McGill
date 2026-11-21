"""Google sign-in + trusted contacts, offline (fake Google, in-memory store)."""
import json
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MemoryStore
from app.google_auth import SCOPES, GoogleAuth, TokenResult
from app.main import create_app

CLIENT_JSON = {"web": {
    "client_id": "test-client.apps.googleusercontent.com",
    "client_secret": "test-secret",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://localhost:8000/api/google/callback"],
}}


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(json.dumps(CLIENT_JSON))
    settings = Settings(google_api_key=None, route_mode="offline",
                        google_oauth_client_file=path, token_encryption_key=Fernet.generate_key().decode())
    store = MemoryStore()
    calls = []

    def fake_exchange(code, verifier):
        calls.append((code, verifier))
        if code == "bad":
            raise RuntimeError("invalid_grant")
        scopes = SCOPES if code != "partial" else [s for s in SCOPES if "gmail" not in s]
        return TokenResult("refresh-123", scopes, "margaret@example.com")

    google = GoogleAuth(settings, store, exchange=fake_exchange)
    client = TestClient(create_app(settings, store=store, google=google), follow_redirects=False)
    return client, store, google, calls


def _connect(client, **params):
    r = client.get("/api/google/connect", params=params)
    assert r.status_code == 307
    return parse_qs(urlparse(r.headers["location"]).query)


# ---------------------------------------------------------------- config / health
def test_health_reports_memory_db_and_unconfigured_google(client):
    h = client.get("/api/health").json()
    assert h["database"] == "memory" and h["database_ok"] is True
    assert h["google_oauth_configured"] is False


def test_connect_without_client_file_is_503(client):
    r = client.get("/api/google/connect")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "google_oauth_not_configured"
    assert client.get("/api/google/status").json() == {
        "configured": False, "problem": "GOOGLE_OAUTH_CLIENT_FILE is not set",
        "connected": False, "required_scopes": SCOPES}


def test_bad_encryption_key_is_reported(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(CLIENT_JSON))
    g = GoogleAuth(Settings(google_oauth_client_file=path, token_encryption_key="nope"), MemoryStore())
    assert not g.configured and "Fernet" in g.problem


def test_settings_read_relative_client_path(monkeypatch):
    from app.config import BACKEND_DIR
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_FILE", "secrets/x.json")
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_x")
    s = Settings.from_env()
    assert s.google_oauth_client_file == BACKEND_DIR / "secrets/x.json"
    assert s.supabase_enabled


# ---------------------------------------------------------------- OAuth flow
def test_connect_redirects_to_google_with_offline_access_and_pkce(setup):
    client, *_ = setup
    q = _connect(client)
    assert q["client_id"] == ["test-client.apps.googleusercontent.com"]
    assert q["redirect_uri"] == ["http://localhost:8000/api/google/callback"]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert set(q["scope"][0].split()) == set(SCOPES)
    assert q["code_challenge_method"] == ["S256"] and q["state"][0]


def test_connect_json_mode_for_frontends(setup):
    client, *_ = setup
    r = client.get("/api/google/connect", params={"redirect": "false"})
    assert r.status_code == 200 and r.json()["auth_url"].startswith("https://accounts.google.com/")


def test_callback_stores_encrypted_token_and_reports_connected(setup):
    client, store, google, calls = setup
    state = _connect(client, person_name="Margaret")["state"][0]
    r = client.get("/api/google/callback", params={"state": state, "code": "good"})
    assert r.status_code == 200 and "margaret@example.com" in r.text
    assert calls and calls[0][0] == "good" and len(calls[0][1]) >= 43  # PKCE verifier passed through

    row = store.get_google_account()
    assert row["refresh_token_enc"] != "refresh-123"
    assert google.cipher.decrypt(row["refresh_token_enc"]) == "refresh-123"
    s = client.get("/api/google/status").json()
    assert s["connected"] and s["google_email"] == "margaret@example.com"
    assert s["person_name"] == "Margaret" and s["missing_scopes"] == []

    creds = google.credentials()
    assert creds.refresh_token == "refresh-123" and creds.client_id.startswith("test-client")


def test_state_is_single_use_and_unknown_state_rejected(setup):
    client, *_ = setup
    state = _connect(client)["state"][0]
    assert client.get("/api/google/callback", params={"state": state, "code": "good"}).status_code == 200
    again = client.get("/api/google/callback", params={"state": state, "code": "good"})
    assert again.status_code == 400 and "expired" in again.text
    assert client.get("/api/google/callback", params={"state": "forged", "code": "good"}).status_code == 400


def test_user_clicking_cancel_on_google_shows_error(setup):
    client, store, *_ = setup
    state = _connect(client)["state"][0]
    r = client.get("/api/google/callback", params={"state": state, "error": "access_denied"})
    assert r.status_code == 400 and "access_denied" in r.text
    assert store.get_google_account() is None


def test_failed_token_exchange_is_502(setup):
    client, store, *_ = setup
    state = _connect(client)["state"][0]
    r = client.get("/api/google/callback", params={"state": state, "code": "bad"})
    assert r.status_code == 502 and store.get_google_account() is None


def test_unticked_permissions_are_reported(setup):
    client, *_ = setup
    state = _connect(client)["state"][0]
    r = client.get("/api/google/callback", params={"state": state, "code": "partial"})
    assert "gmail.send" in r.text
    assert client.get("/api/google/status").json()["missing_scopes"] == [
        "https://www.googleapis.com/auth/gmail.send"]


def test_reconnect_replaces_token_and_disconnect_removes_it(setup, monkeypatch):
    client, store, google, _ = setup
    for _ in range(2):
        state = _connect(client)["state"][0]
        client.get("/api/google/callback", params={"state": state, "code": "good"})
    assert len(store.google_accounts) == 1
    revoked = []
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, data, timeout: revoked.append(data["token"]))
    assert client.post("/api/google/disconnect").json() == {"connected": False}
    assert revoked == ["refresh-123"] and store.get_google_account() is None


def test_credentials_before_connecting_is_409(setup):
    _, _, google, _ = setup
    from app.errors import ApiError
    with pytest.raises(ApiError) as e:
        google.credentials()
    assert e.value.code == "google_not_connected"


def test_custom_done_url_redirects_after_connect(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(CLIENT_JSON))
    settings = Settings(google_oauth_client_file=path, token_encryption_key=Fernet.generate_key().decode(),
                        google_oauth_done_url="http://localhost:5173/setup", route_mode="offline")
    store = MemoryStore()
    g = GoogleAuth(settings, store, exchange=lambda c, v: TokenResult("r", SCOPES, "a@b.co"))
    client = TestClient(create_app(settings, store=store, google=g), follow_redirects=False)
    state = _connect(client)["state"][0]
    r = client.get("/api/google/callback", params={"state": state, "code": "x"})
    assert r.headers["location"] == "http://localhost:5173/setup?google=connected"


# ---------------------------------------------------------------- contacts
def _add(client, name, email, priority, **kw):
    return client.post("/api/contacts", json={"name": name, "email": email, "priority": priority, **kw})


def test_contacts_crud_and_priority_order(client):
    b = _add(client, "Ben", "ben@example.com", 2, relationship="son").json()
    a = _add(client, "Anna", "anna@example.com", 1, relationship="daughter").json()
    assert [c["name"] for c in client.get("/api/contacts").json()] == ["Anna", "Ben"]

    r = client.patch(f"/api/contacts/{b['id']}", json={"relationship": "grandson"})
    assert r.status_code == 200 and r.json()["relationship"] == "grandson" and r.json()["priority"] == 2
    assert client.get(f"/api/contacts/{a['id']}").json()["email"] == "anna@example.com"

    assert client.delete(f"/api/contacts/{a['id']}").status_code == 204
    assert client.get(f"/api/contacts/{a['id']}").status_code == 404
    assert [c["name"] for c in client.get("/api/contacts").json()] == ["Ben"]


def test_duplicate_priority_or_email_is_409(client):
    _add(client, "Anna", "anna@example.com", 1)
    r = _add(client, "Ben", "ben@example.com", 1)
    assert r.status_code == 409 and r.json()["error"]["code"] == "priority_taken"
    r = _add(client, "Anna 2", "ANNA@example.com", 2)
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    ben = _add(client, "Ben", "ben@example.com", 2).json()
    r = client.patch(f"/api/contacts/{ben['id']}", json={"priority": 1})
    assert r.status_code == 409


def test_reorder_contacts(client):
    ids = [_add(client, n, f"{n}@example.com", i).json()["id"] for i, n in enumerate(["a", "b", "c"], 1)]
    r = client.put("/api/contacts/order", json={"ids": [ids[2], ids[0], ids[1]]})
    assert [(c["name"], c["priority"]) for c in r.json()] == [("c", 1), ("a", 2), ("b", 3)]
    bad = client.put("/api/contacts/order", json={"ids": ids[:2]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_order"


def test_contact_validation(client):
    r = _add(client, "X", "not-an-email", 1)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "email"
    assert _add(client, "X", "x@example.com", 0).status_code == 422
    assert client.patch("/api/contacts/nope", json={"name": "Y"}).status_code == 404
