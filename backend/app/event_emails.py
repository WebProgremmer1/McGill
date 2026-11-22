"""Calendar event emails: before every timed event in Margaret's Google Calendar, send her own
Gmail a reminder with everything the calendar knows: what, when, who (with the relationship for
trusted contacts), where, and the description.

- Sent VISIT_REMINDER_LEAD_MIN (20) minutes before the start, once per event. If the event is
  moved, the new time gets its own email. Events already started, all-day and cancelled are skipped.
- Each email is logged in notifications_sent (kind "calendar_event:<id>:<start>"), which is
  also what stops repeats, including across restarts.
- A Gmail failure is logged with its error and not retried (so a broken send can't loop).
CALENDAR_EMAILS=off turns it off.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import Settings
from .db import Row, Store
from .errors import ApiError
from .mailer import Mailer
from .reminders import VisitReminders, _plain, clock_text, local_start

log = logging.getLogger(__name__)
DETAILS_MAX = 1500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventEmails:
    def __init__(self, store: Store, mailer: Mailer, reminders: VisitReminders, settings: Settings,
                 clock: Callable[[], datetime] | None = None):
        self.store = store
        self.mailer = mailer
        self.reminders = reminders
        self.settings = settings
        self.clock = clock or _utcnow
        self._lock = threading.Lock()

    def tick(self) -> int:
        """Email every event that is now inside the lead window. Returns how many were sent."""
        if not self.settings.calendar_emails:
            return 0
        google = self.reminders.google
        if google is not None and not google.configured:
            return 0
        acct = self.store.get_google_account()
        if not acct or not acct.get("google_email") or acct.get("status") == "needs_reconnect":
            return 0
        with self._lock:
            now = self.clock()
            try:
                events, cal_tz = self.reminders.events(now)
            except Exception as e:  # noqa: BLE001 - try again on the next tick
                log.warning("calendar emails: couldn't read the calendar: %s", e)
                return 0
            lead = timedelta(minutes=self.settings.visit_reminder_lead_min)
            due = []
            for e in events:
                local = local_start(e, cal_tz)
                if e.get("status") == "cancelled" or local is None:
                    continue
                if local - lead <= now < local:
                    due.append((local, e))
            due.sort(key=lambda d: d[0])
            return sum(self._email(acct, e, local, now) for local, e in due)

    # ------------------------------------------------------------ one event
    def _email(self, acct: Row, e: dict, local: datetime, now: datetime) -> bool:
        me = acct["google_email"]
        start_utc = local.astimezone(timezone.utc).isoformat()
        note = self.store.claim_notification({
            "escalation_id": None, "journey_id": "calendar", "recipient": me,
            "kind": f"calendar_event:{e.get('id')}:{start_utc}"})
        if not note:
            return False  # already emailed for this event at this time
        subject, text = self.compose(acct, e, local, now)
        try:
            msg_id = self.mailer.send(me, subject, text)
            self.store.update_notification(note["id"], {"gmail_message_id": msg_id})
            return True
        except Exception as ex:  # noqa: BLE001
            message = ex.message if isinstance(ex, ApiError) else str(ex)
            log.warning("calendar email for %s failed: %s", e.get("id"), message)
            self.store.update_notification(note["id"], {"error": message[:500] or type(ex).__name__})
            return False

    def compose(self, acct: Row, e: dict, local: datetime, now: datetime) -> tuple[str, str]:
        name = ((acct.get("person_name") or "").split() or ["there"])[0]
        title = (e.get("summary") or "").strip() or "An event"
        clock = clock_text(local)
        minutes = max(0, round((local - now).total_seconds() / 60))
        lines = [f"Hi {name},", "",
                 f"In {minutes} minute{'s' if minutes != 1 else ''}, at {clock}: {title}."]
        who = self._who(e, acct["google_email"])
        if who:
            lines.append(f"Who: {who}")
        where = _plain(e.get("location"))
        if where:
            lines.append(f"Where: {where}")
        details = _plain(e.get("description"))
        if details:
            if len(details) > DETAILS_MAX:
                details = details[:DETAILS_MAX - 1].rstrip() + "…"
            lines.append(f"Details: {details}")
        lines += ["", "— Walk Safety (from your Google Calendar)"]
        return f"Reminder: {title} at {clock}", "\n".join(lines)

    def _who(self, e: dict, me: str) -> str:
        contacts = {c["email"].lower(): c for c in self.store.list_contacts()}
        people = []
        for a in e.get("attendees") or []:
            email = (a.get("email") or "").lower()
            if (a.get("self") or email == me.lower() or a.get("resource")
                    or a.get("responseStatus") == "declined"):
                continue
            c = contacts.get(email)
            if c:
                rel = (c.get("relationship") or "").strip()
                people.append((c["priority"], f"{c['name']} (your {rel})" if rel else c["name"]))
            else:
                people.append((10_000, a.get("displayName") or a.get("email")))
        people.sort(key=lambda p: p[0])  # trusted contacts first, by priority
        return ", ".join(p[1] for p in people if p[1])
