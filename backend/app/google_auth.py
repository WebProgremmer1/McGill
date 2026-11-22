"""Google sign-in (OAuth 2.0) for the person's Gmail and Calendar.

Flow:
  1. GET /api/google/connect   -> redirect to Google's consent screen
  2. Google -> GET /api/google/callback?code=...&state=...
  3. We swap the code for a refresh token, encrypt it, and save it in the store.
  4. Later, `GoogleAuth.credentials()` rebuilds working credentials from that
     refresh token; Google's library renews the short-lived access token itself.

The OAuth client comes from the JSON file downloaded from Google Cloud
(GOOGLE_OAUTH_CLIENT_FILE). The refresh token is encrypted with
TOKEN_ENCRYPTION_KEY (Fernet), so a database leak alone does not expose Google access.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings
from .db import DEFAULT_PERSON, Store
from .errors import ApiError

# Google may return scopes in a different order or include earlier grants.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
]
STATE_TTL_S = 600
ID_TOKEN_CLOCK_SKEW_S = 10  # a PC clock a few seconds behind Google must not fail sign-in
SESSION_TTL_S = 8 * 60 * 60
SESSION_COOKIE = "whats_next_session"
OAUTH_STATE_COOKIE = "whats_next_oauth_state"
log = logging.getLogger("google_auth")


@dataclass
class TokenResult:
    refresh_token: str
    scopes: list[str]
    email: str


Exchange = Callable[[str, str], TokenResult]  # (code, code_verifier) -> TokenResult


def _failure_code(error: Exception) -> str:
    """A safe label for logs. Never returns the provider's message, which can contain token data."""
    code = getattr(error, "error", None)
    if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,40}", code):
        return code
    text = str(error).lower()
    for phrase, label in (("used too early", "id_token_used_too_early"), ("token expired", "id_token_expired"),
                          ("audience", "id_token_wrong_audience"), ("signature", "id_token_bad_signature")):
        if phrase in text:
            return label
    return "unclassified"


class TokenCipher:
    def __init__(self, key: str):
        try:
            self._f = Fernet(key.encode())
        except (ValueError, TypeError):
            raise ValueError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key "
                             "(generate one with: python -m app.google_auth --new-key)") from None

    def encrypt(self, text: str) -> str:
        return self._f.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken:
            raise ApiError(500, "token_decrypt_failed",
                           "Stored Google token can't be decrypted (TOKEN_ENCRYPTION_KEY changed?). "
                           "Reconnect Google.") from None


def load_client_config(path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    cfg = data.get("web") or data.get("installed")
    if not cfg or not cfg.get("client_id") or not cfg.get("client_secret"):
        raise ValueError(f"{path.name} is not a Google OAuth client file")
    return data


class GoogleAuth:
    def __init__(self, settings: Settings, store: Store, exchange: Exchange | None = None):
        self.settings = settings
        self.store = store
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._client: dict[str, Any] | None = None
        self.problem: str | None = None
        self.cipher: TokenCipher | None = None
        self._sessions: Fernet | None = None

        path = settings.google_oauth_client_file
        if not path:
            self.problem = "GOOGLE_OAUTH_CLIENT_FILE is not set"
        elif not path.exists():
            self.problem = f"OAuth client file not found: {path.name}"
        else:
            try:
                self._client = load_client_config(path)
            except (ValueError, json.JSONDecodeError) as e:
                self.problem = str(e)
        if not self.problem:
            if not settings.token_encryption_key:
                self.problem = "TOKEN_ENCRYPTION_KEY is not set"
            else:
                try:
                    self.cipher = TokenCipher(settings.token_encryption_key)
                    # Session cookies use a derived key, so stored Google tokens can't be replayed as sessions.
                    digest = hashlib.sha256(b"whats-next-session:" + settings.token_encryption_key.encode()).digest()
                    self._sessions = Fernet(base64.urlsafe_b64encode(digest))
                except ValueError as e:
                    self.problem = str(e)
        self._exchange = exchange or self._google_exchange

    # ------------------------------------------------------------ helpers
    @property
    def configured(self) -> bool:
        return self.problem is None

    def _require(self) -> None:
        if not self.configured:
            raise ApiError(503, "google_oauth_not_configured", self.problem or "")

    @property
    def _cfg(self) -> dict[str, Any]:
        assert self._client
        return self._client.get("web") or self._client["installed"]

    def _flow(self, state: str | None = None):
        from google_auth_oauthlib.flow import Flow
        return Flow.from_client_config(self._client, scopes=SCOPES, state=state,
                                       redirect_uri=self.settings.google_oauth_redirect_uri)

    # ------------------------------------------------------------ connect
    def start(self, person_name: str | None = None, person_key: str = DEFAULT_PERSON) -> str:
        """Return the Google consent URL to send the browser to."""
        self._require()
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)  # PKCE
        flow = self._flow(state)
        flow.code_verifier = verifier
        # No include_granted_scopes: an earlier grant must not widen this token.
        url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        now = time.time()
        with self._lock:
            self._states = {k: v for k, v in self._states.items() if v["at"] > now - STATE_TTL_S}
            self._states[state] = {"verifier": verifier, "person_name": person_name,
                                   "person_key": person_key, "at": now}
        return url

    def finish(self, state: str | None, code: str | None, error: str | None = None) -> dict[str, Any]:
        """Handle Google's redirect. Returns the public account status."""
        self._require()
        if error:
            raise ApiError(400, "google_denied", f"Google sign-in was not completed: {error}")
        with self._lock:
            entry = self._states.pop(state or "", None)
        if not entry or entry["at"] < time.time() - STATE_TTL_S:
            raise ApiError(400, "invalid_state",
                           "This sign-in link expired or was already used. Start again from /api/google/connect.")
        if not code:
            raise ApiError(400, "missing_code", "Google did not return an authorization code.")
        try:
            result = self._exchange(code, entry["verifier"])
        except ApiError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Google token exchange failed: %s code=%s", type(e).__name__, _failure_code(e))
            raise ApiError(502, "google_token_exchange_failed", "Google rejected the sign-in. Try again.") from None
        allowed = (self.settings.google_allowed_email or "").strip().lower()
        if not allowed or result.email.strip().lower() != allowed:
            raise ApiError(403, "google_account_not_allowed", "This Google account isn't approved for this demo.")
        self.store.save_google_account({
            "person_key": entry["person_key"],
            "person_name": entry["person_name"],
            "google_email": result.email,
            "refresh_token_enc": self.cipher.encrypt(result.refresh_token),
            "scopes": sorted(result.scopes),
            "status": "connected",
        })
        return self.status(entry["person_key"])

    def _google_exchange(self, code: str, verifier: str) -> TokenResult:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        flow = self._flow()
        flow.code_verifier = verifier
        flow.fetch_token(code=code)
        creds = flow.credentials
        if not creds.refresh_token:
            raise ApiError(400, "no_refresh_token",
                           "Google did not return a refresh token. Remove the app at "
                           "https://myaccount.google.com/permissions and connect again.")
        info = id_token.verify_oauth2_token(creds.id_token, Request(), self._cfg["client_id"],
                                            clock_skew_in_seconds=ID_TOKEN_CLOCK_SKEW_S)
        if not info.get("email_verified"):
            raise ApiError(403, "google_email_not_verified", "This Google account's email isn't verified.")
        scopes = list(getattr(creds, "granted_scopes", None) or creds.scopes or [])
        return TokenResult(creds.refresh_token, scopes, info.get("email", ""))

    # ------------------------------------------------------------ app session
    def issue_session(self, person_key: str = DEFAULT_PERSON) -> str:
        """An encrypted cookie value proving this browser completed Connect Google."""
        self._require()
        acct = self.store.get_google_account(person_key)
        if not acct:
            raise ApiError(409, "google_not_connected", "Connect Google first: open /api/google/connect")
        payload = json.dumps({"person_key": person_key, "email": acct["google_email"].strip().lower()})
        return self._sessions.encrypt(payload.encode()).decode()

    def read_session(self, token: str | None) -> dict[str, str] | None:
        """Valid only while the same approved account is still connected."""
        if not token or not self.configured or not self._sessions:
            return None
        try:
            data = json.loads(self._sessions.decrypt(token.encode(), ttl=SESSION_TTL_S))
            acct = self.store.get_google_account(data["person_key"])
        except InvalidToken:
            return None
        except Exception as e:  # noqa: BLE001 - a storage problem must fail closed
            log.warning("Session check failed: %s", type(e).__name__)
            return None
        allowed = (self.settings.google_allowed_email or "").strip().lower()
        email = (acct or {}).get("google_email", "").strip().lower()
        if not acct or acct.get("status") != "connected" or not allowed or email != allowed or email != data.get("email"):
            return None
        return {"person_key": data["person_key"], "email": email}

    def approved_account(self, person_key: str = DEFAULT_PERSON) -> dict[str, Any] | None:
        """The stored account, only while it is connected and is the one approved address."""
        allowed = (self.settings.google_allowed_email or "").strip().lower()
        acct = self.store.get_google_account(person_key)
        email = (acct or {}).get("google_email", "").strip().lower()
        return acct if acct and acct.get("status") == "connected" and allowed and email == allowed else None

    # ------------------------------------------------------------ use
    def credentials(self, person_key: str = DEFAULT_PERSON):
        """Working google.oauth2 Credentials for Gmail and Calendar API calls."""
        self._require()
        from google.oauth2.credentials import Credentials

        acct = self.store.get_google_account(person_key)
        if not acct:
            raise ApiError(409, "google_not_connected", "Connect Google first: open /api/google/connect")
        return Credentials(
            token=None,
            refresh_token=self.cipher.decrypt(acct["refresh_token_enc"]),
            token_uri=self._cfg.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=self._cfg["client_id"],
            client_secret=self._cfg["client_secret"],
            scopes=acct.get("scopes") or SCOPES,
        )

    def check(self, person_key: str = DEFAULT_PERSON) -> bool:
        """Refresh the access token now. Marks the account 'needs_reconnect' if Google refuses."""
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request

        creds = self.credentials(person_key)
        try:
            creds.refresh(Request())
            return True
        except RefreshError:
            acct = self.store.get_google_account(person_key)
            if acct:
                self.store.save_google_account({**_strip(acct), "status": "needs_reconnect"})
            return False

    def status(self, person_key: str = DEFAULT_PERSON, check: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {"configured": self.configured, "problem": self.problem,
                               "connected": False, "required_scopes": SCOPES}
        if not self.configured:
            return out
        acct = self.store.get_google_account(person_key)
        if not acct:
            return out
        token_ok = self.check(person_key) if check else None
        acct = self.store.get_google_account(person_key) or acct
        granted = set(acct.get("scopes") or [])
        out.update({
            "connected": acct["status"] == "connected",
            "status": acct["status"],
            "google_email": acct["google_email"],
            "person_name": acct.get("person_name"),
            "scopes": sorted(granted),
            "missing_scopes": [s for s in SCOPES if s not in granted],
            "connected_at": acct.get("connected_at"),
            "token_ok": token_ok,
        })
        return out

    def disconnect(self, person_key: str = DEFAULT_PERSON) -> None:
        acct = self.store.get_google_account(person_key)
        if not acct:
            return
        if self.configured:
            try:  # best effort: also revoke on Google's side
                import httpx
                httpx.post("https://oauth2.googleapis.com/revoke",
                           data={"token": self.cipher.decrypt(acct["refresh_token_enc"])}, timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self.store.delete_google_account(person_key)


def _strip(acct: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in acct.items() if k not in ("id", "connected_at", "updated_at")}


if __name__ == "__main__":
    import sys
    if "--new-key" in sys.argv:
        print(Fernet.generate_key().decode())
