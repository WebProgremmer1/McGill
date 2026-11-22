"""Gmail help emails and one read-only Calendar event for the connected test account.

Logs record only an error type. They never include tokens, addresses, or event details.
"""
from __future__ import annotations

import base64
import logging
import re
import threading
import time
from datetime import date, datetime, timezone
from email.message import EmailMessage
from typing import Any, Callable

from .config import Settings
from .google_auth import GoogleAuth
from .models import Alert

log = logging.getLogger("google_services")

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CALENDAR_CACHE_S = 30

# Deliberately generic: no name, health details, address, destination, or location.
HELP_SUBJECT = "What's Next? help request"
HELP_BODY = (
    "Someone using What's Next? asked for help.\n\n"
    "Please open the Care dashboard or contact them directly.\n\n"
    "This prototype is not monitored. If this may be an emergency, call your local emergency number.\n"
)

GmailSender = Callable[[Any, str], str]             # (credentials, raw message) -> Gmail message ID
CalendarLister = Callable[[Any, str, str], list]    # (credentials, calendar ID, time_min) -> events


def _authorized_http(credentials: Any):
    import google_auth_httplib2
    import httplib2
    return google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=10))


def gmail_send(credentials: Any, raw: str) -> str:
    from googleapiclient.discovery import build

    service = build("gmail", "v1", http=_authorized_http(credentials), cache_discovery=False, static_discovery=True)
    return service.users().messages().send(userId="me", body={"raw": raw}).execute()["id"]


def calendar_list(credentials: Any, calendar_id: str, time_min: str) -> list[dict[str, Any]]:
    from googleapiclient.discovery import build

    service = build("calendar", "v3", http=_authorized_http(credentials), cache_discovery=False, static_discovery=True)
    result = service.events().list(
        calendarId=calendar_id, timeMin=time_min, maxResults=10, singleEvents=True,
        orderBy="startTime", fields="items(summary,start)",
    ).execute()
    return result.get("items", [])


def _has_scope(google: GoogleAuth, session: dict[str, str], scope: str) -> bool:
    account = google.store.get_google_account(session["person_key"])
    return bool(account and scope in (account.get("scopes") or []))


class HelpEmailer:
    """Sends at most one email per saved help alert."""

    def __init__(self, settings: Settings, google: GoogleAuth, sender: GmailSender | None = None):
        self.settings = settings
        self.google = google
        self._send = sender or gmail_send
        self._claimed: set[str] = set()
        self._lock = threading.Lock()

    @property
    def recipient(self) -> str | None:
        value = self.settings.help_email_to or ""
        return value if EMAIL_ADDRESS.match(value) else None

    def problem(self, session: dict[str, str] | None) -> str | None:
        if not session:
            return "No Google session."
        if not self.recipient:
            return "HELP_EMAIL_TO is not set."
        if not self.settings.help_email_consent:
            return "HELP_EMAIL_CONSENT is not yes."
        if not _has_scope(self.google, session, GMAIL_SCOPE):
            return "Gmail permission was not granted."
        return None

    def claim(self, alert: Alert, session: dict[str, str] | None) -> bool:
        """Reserve this alert's one email. Repeated clicks and concurrent requests get False."""
        try:
            if self.problem(session):
                return False
        except Exception as error:  # noqa: BLE001 - a storage problem must not block the saved alert
            log.warning("Help email check failed: %s", type(error).__name__)
            return False
        with self._lock:
            if alert.id in self._claimed:
                return False
            self._claimed.add(alert.id)
            alert.email_status = "sending"
            return True

    def send(self, alert: Alert, session: dict[str, str]) -> None:
        try:
            message = EmailMessage()
            message["To"] = self.settings.help_email_to
            message["Subject"] = HELP_SUBJECT
            message.set_content(HELP_BODY)
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            message_id = self._send(self.google.credentials(session["person_key"]), raw)
            if not message_id:
                raise RuntimeError("Gmail returned no message ID")
            alert.email_status = "accepted"
        except Exception as error:  # noqa: BLE001 - the dashboard alert stays saved
            log.warning("Help email failed: %s", type(error).__name__)
            alert.email_status = "failed"


class CalendarReader:
    """Reads the next event that has not started from the configured calendar."""

    def __init__(self, settings: Settings, google: GoogleAuth, lister: CalendarLister | None = None):
        self.settings = settings
        self.google = google
        self._list = lister or calendar_list
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def next_event(self, session: dict[str, str]) -> dict[str, Any]:
        calendar_id = self.settings.google_calendar_id
        if not calendar_id:
            return {"state": "not_configured"}
        key = f"{session['person_key']}:{calendar_id}"
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            if not _has_scope(self.google, session, CALENDAR_SCOPE):
                return {"state": "unavailable"}
            now = datetime.now(timezone.utc)
            items = self._list(self.google.credentials(session["person_key"]), calendar_id,
                               now.isoformat().replace("+00:00", "Z"))
            event = next((view for view in map(lambda item: _event_view(item, now), items) if view), None)
        except Exception as error:  # noqa: BLE001 - the Patient dashboard shows an unavailable state
            log.warning("Calendar read failed: %s", type(error).__name__)
            return {"state": "unavailable"}
        result = {"state": "ok", "event": event} if event else {"state": "empty"}
        self._cache[key] = (time.monotonic() + CALENDAR_CACHE_S, result)
        return result


def _event_view(item: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    start = item.get("start") or {}
    title = (item.get("summary") or "Untitled event").strip()[:120] or "Untitled event"
    if start.get("dateTime"):
        value = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return {"title": title, "start": start["dateTime"], "all_day": False} if value >= now else None
    if start.get("date"):
        return {"title": title, "start": start["date"], "all_day": True} \
            if date.fromisoformat(start["date"]) > now.astimezone().date() else None
    return None
