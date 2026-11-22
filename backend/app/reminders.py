"""Visit reminders from the person's Google Calendar (calendar.readonly).

A timed event is a *visit* when one of its guests is a trusted contact who hasn't declined.
The contact gives the photo, name and relationship; the event gives the time and the reason.
Shown on the phone from VISIT_REMINDER_LEAD_MIN before the start until VISIT_REMINDER_GRACE_MIN after.
Design: docs/superpowers/specs/2026-11-21-visit-reminders-design.md
"""
from __future__ import annotations

import html
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Settings
from .db import Row, Store
from .errors import ApiError

CACHE_S = 60
LOOKAHEAD = timedelta(hours=24)
REASON_MAX = 200

# (time_min, time_max) -> (events in Google's format, the calendar's time zone)
Fetch = Callable[[datetime, datetime], tuple[list[dict[str, Any]], str | None]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _plain(text: str | None) -> str:
    """Calendar descriptions can be HTML. Keep the words only."""
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", " ", text or "", flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\s+", " ", text).strip()


def local_start(e: dict, cal_tz: str | None) -> datetime | None:
    """An event's start time in the calendar's own time zone (None for all-day events)."""
    start = (e.get("start") or {}).get("dateTime")
    if not start:
        return None
    starts = datetime.fromisoformat(start.replace("Z", "+00:00"))
    tz_name = (e.get("start") or {}).get("timeZone") or cal_tz
    try:
        return starts.astimezone(ZoneInfo(tz_name)) if tz_name else starts
    except Exception:  # noqa: BLE001 - unknown zone name: keep Google's own offset
        return starts


def clock_text(t: datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _first(name: str) -> str:
    return name.split()[0] if name.strip() else name


def _who(c: Row) -> str:
    rel = (c.get("relationship") or "").strip()
    return f"{_first(c['name'])}, your {rel}," if rel else _first(c["name"])


class VisitReminders:
    def __init__(self, store: Store, settings: Settings, google: Any = None,
                 fetch: Fetch | None = None, clock: Callable[[], datetime] | None = None):
        self.store = store
        self.settings = settings
        self.google = google
        self._fetch = fetch or self._google_fetch
        self.clock = clock or _utcnow
        self._cache: tuple[float, list, str | None] | None = None
        self._lock = threading.Lock()

    def clear_cache(self) -> None:
        self._cache = None

    # ------------------------------------------------------------ Google
    def _google_fetch(self, time_min: datetime, time_max: datetime):
        from googleapiclient.discovery import build

        from .google_services import _authorized_http

        if self.google is None:
            raise ApiError(503, "google_oauth_not_configured", "Google sign-in is not set up.")
        cal = build("calendar", "v3", http=_authorized_http(self.google.credentials()),
                    cache_discovery=False, static_discovery=True)
        res = cal.events().list(calendarId=self.settings.google_calendar_id or "primary", timeMin=time_min.isoformat(),
                                timeMax=time_max.isoformat(), singleEvents=True,
                                orderBy="startTime", maxResults=100).execute()
        return res.get("items", []), res.get("timeZone")

    def events(self, now: datetime):
        """(events, calendar time zone) around `now`, from Google at most once a minute."""
        return self._events(now)

    def _events(self, now: datetime):
        with self._lock:
            if self._cache and time.monotonic() - self._cache[0] < CACHE_S:
                return self._cache[1], self._cache[2]
            grace = timedelta(minutes=self.settings.visit_reminder_grace_min)
            events, tz = self._fetch(now - grace, now + LOOKAHEAD)
            self._cache = (time.monotonic(), events, tz)
            return events, tz

    # ------------------------------------------------------------ public
    def list(self) -> dict[str, Any]:
        """Visits in the next 24 h; `show_now` marks the ones to put on the phone."""
        if self.google is not None and not self.google.configured:
            return {"available": False, "problem": self.google.problem, "reminders": []}
        if self.google is not None and not self.store.get_google_account():
            return {"available": False, "problem": "Google is not connected.", "reminders": []}
        now = self.clock()
        try:
            events, cal_tz = self._events(now)
        except Exception as e:  # noqa: BLE001 - the phone page must keep working
            msg = e.message if isinstance(e, ApiError) else str(e)
            return {"available": False, "problem": f"Couldn't read the calendar: {msg}", "reminders": []}

        acct = self.store.get_google_account() or {}
        me = (acct.get("google_email") or "").lower()
        contacts = {c["email"].lower(): c for c in self.store.list_contacts()}
        out = [r for e in events if (r := self._visit(e, contacts, me, cal_tz, now))]
        out.sort(key=lambda r: r["arrives_at"])
        return {"available": True, "problem": None, "reminders": out}

    # ------------------------------------------------------------ one event
    def _visit(self, e: dict, contacts: dict[str, Row], me: str, cal_tz: str | None,
               now: datetime) -> dict[str, Any] | None:
        start = (e.get("start") or {}).get("dateTime")
        if e.get("status") == "cancelled" or not start:
            return None  # all-day events have only "date": a stay, not a visit
        visitors = []
        for a in e.get("attendees") or []:
            email = (a.get("email") or "").lower()
            if a.get("self") or email == me or a.get("responseStatus") == "declined":
                continue
            if email in contacts:
                visitors.append(contacts[email])
        if not visitors:
            return None
        visitors.sort(key=lambda c: c["priority"])

        local = local_start(e, cal_tz)
        starts = local.astimezone(timezone.utc)
        lead = timedelta(minutes=self.settings.visit_reminder_lead_min)
        grace = timedelta(minutes=self.settings.visit_reminder_grace_min)
        if now > starts + grace:
            return None

        title = (e.get("summary") or "").strip()
        details = _plain(e.get("description"))
        reason = " — ".join(p for p in (title, details) if p)
        if len(reason) > REASON_MAX:
            reason = reason[:REASON_MAX - 1].rstrip() + "…"
        clock = clock_text(local)

        main, others = visitors[0], visitors[1:]
        parts = [_who(c) for c in visitors]
        if len(parts) == 1:
            names = parts[0]
        else:  # "Anna, your daughter, and Ben, your son," / "Anna, Ben, and Cara"
            names = " ".join(p if p.endswith(",") else p + "," for p in parts[:-1]) + " and " + parts[-1]
        spoken = f"{names} {'is' if not others else 'are'} coming to visit at {clock}."
        for part in (title, details):
            if part:
                spoken += f" {part.rstrip('.')}."

        return {
            "event_id": e.get("id"),
            "show_now": starts - lead <= now <= starts + grace,
            "arrives_at": starts.astimezone(timezone.utc).isoformat(),
            "arrival_text": clock,
            "minutes_until": round((starts - now).total_seconds() / 60),
            "visitor": self._public(main),
            "with": [self._public(c) for c in others],
            "title": title,
            "reason": reason,
            "read_aloud": spoken,
        }

    @staticmethod
    def _public(c: Row) -> dict[str, Any]:
        return {"name": c["name"], "relationship": c.get("relationship"),
                "photo_url": c.get("photo_url"), "email": c["email"]}
