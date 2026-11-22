"""Email escalation: who gets emailed, when, and when it stops.

Rules (design: docs/superpowers/specs/2026-11-21-google-escalation-design.md):
- Medium risk (a check-in appears): email the person "are you okay?". If the check-in is still
  unanswered after CHECKIN_REPLY_TIMEOUT_S, start emailing family one at a time.
- High risk (a caregiver alert): email trusted contact #1. If nobody clicks "I'm on it" within
  ESCALATION_STEP_S, email the next one by priority. After the last contact it just stops.
- Score 90-100: email every contact at once. The help button has its own single email (HelpEmailer),
  so here it only stops this journey's timed family emails.
- "I'm on it" (from any contact) or acknowledging the alert on the dashboard stops it for everyone.
- "I'm okay" from the person after family was emailed: send them an "all good" update and close.
  Arriving at the destination does the same with an "arrived" update. A walk ended in the app
  while she is NOT at the destination sends an "ended" update with her last location instead.

Delays use the wall clock (`clock`), not GPS time. State lives in the store (Supabase), and every
escalation keeps a snapshot of the journey, so a restarted server carries on from the database.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import Settings
from .db import Row, Store
from .errors import ApiError, not_found
from .mailer import Mailer
from .models import DISCLAIMER, Journey
from .geo import distance_m
from .risk import ARRIVED_M, CRITICAL_MIN

log = logging.getLogger(__name__)

FAMILY_KINDS = ("sequential", "all")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def snapshot(j: Journey) -> dict[str, Any]:
    """What the emails need, saved with the escalation so it works after a restart."""
    loc = j.latest_location
    return {
        "user_name": j.user_name,
        "start": j.start.name,
        "destination": j.destination.name,
        "last_lat": loc.latitude if loc else j.start.latitude,
        "last_lng": loc.longitude if loc else j.start.longitude,
        "last_seen": (loc.timestamp if loc else j.started_at).isoformat(),
        "score": j.risk.score,
        "reasons": [r.description for r in j.risk.reasons if r.points > 0],
        "help_requested": j.help_requested,
    }


class EscalationEngine:
    def __init__(self, store: Store, mailer: Mailer, settings: Settings,
                 clock: Callable[[], datetime] | None = None):
        self.store = store
        self.mailer = mailer
        self.settings = settings
        self.clock = clock or _utcnow
        self._lock = threading.RLock()

    # ============================================================ events from JourneyService
    def on_location(self, j: Journey, checkin_created: bool, alert_created: bool) -> None:
        """Called after every GPS update has been scored."""
        if not j.email_escalation:
            return  # open-demo walks never send real email
        with self._lock:
            esc = self._open(j.id)
            if esc:
                esc = self.store.update_escalation(esc["id"], {"snapshot": snapshot(j)})
            critical = j.risk.score >= CRITICAL_MIN and not j.help_requested
            if not critical:
                j.critical_latched = False
            if critical and not j.critical_latched:
                j.critical_latched = True
                self._everyone(j, esc)
            elif alert_created:
                self._start_sequential(j, esc)
            elif checkin_created and not esc:
                self._ask_person(j)

    def on_help(self, j: Journey) -> None:
        """HelpEmailer sends the one help email. This only stops the timed family emails."""
        if not j.email_escalation:
            return
        with self._lock:
            esc = self._open(j.id)
            if esc:
                self.store.update_escalation(esc["id"], {"tier": "all", "next_step_at": None,
                                                         "snapshot": snapshot(j)})
            else:
                self._create(j, "all")

    def on_reset(self) -> None:
        """The demo was reset: its journeys are gone, so no timer may keep emailing about them."""
        with self._lock:
            for esc in self.store.list_escalations(status="open"):
                self._close(esc)

    def on_checkin_answered(self, j: Journey, okay: bool) -> None:
        with self._lock:
            esc = self._open(j.id)
            if not esc:
                return
            if esc["tier"] == "person":
                self._close(esc)  # she answered in time: family is never bothered
            elif okay:
                self._update_family(esc, snapshot(j), "all_clear")
                self._close(esc)

    def on_journey_end(self, j: Journey, status: str) -> None:
        with self._lock:
            esc = self._open(j.id)
            if not esc:
                return
            if status == "completed" and esc["tier"] != "person":
                here = j.latest_location
                arrived = here is not None and distance_m(here, j.destination) <= ARRIVED_M
                self._update_family(esc, snapshot(j), "arrived" if arrived else "ended")
            self._close(esc)

    def on_alert_acknowledged(self, journey_id: str) -> None:
        """A caregiver acknowledged the alert on the dashboard."""
        with self._lock:
            esc = self._open(journey_id)
            if esc and esc["tier"] != "person":
                self.store.update_escalation(esc["id"], {"status": "acknowledged", "next_step_at": None,
                                                         "closed_at": self.clock().isoformat()})

    # ============================================================ "I'm on it"
    def acknowledge(self, token: str) -> tuple[Row, Row | None]:
        """A contact clicked "I'm on it". Returns (escalation, contact). Safe to repeat."""
        with self._lock:
            note = self.store.find_notification_by_token(hash_token(token or ""))
            if not note:
                raise not_found("ack_token", "(hidden)")
            esc = self.store.get_escalation(note["escalation_id"])
            contact = self._contact_by_email(note["recipient"])
            if esc["status"] == "open":
                esc = self.store.update_escalation(esc["id"], {
                    "status": "acknowledged", "next_step_at": None,
                    "acknowledged_by": contact["id"] if contact else None,
                    "closed_at": self.clock().isoformat()})
            return esc, contact

    # ============================================================ timer
    def tick(self) -> int:
        """Advance every escalation whose next step is due. Returns how many advanced."""
        with self._lock:
            now, moved = self.clock(), 0
            for esc in self.store.list_escalations(status="open"):
                due = _parse(esc.get("next_step_at"))
                if not due or due > now:
                    continue
                try:
                    if esc["tier"] == "person":  # check-in unanswered: start on the family
                        esc = self.store.update_escalation(esc["id"], {"tier": "sequential", "next_priority": 1})
                    self._email_next(esc)
                    moved += 1
                except Exception as error:  # noqa: BLE001 - one bad row must not stop the others
                    log.warning("escalation step failed: %s", type(error).__name__)
            return moved

    # ============================================================ steps
    def _open(self, journey_id: str) -> Row | None:
        rows = self.store.list_escalations(status="open", journey_id=journey_id)
        return rows[0] if rows else None

    def _create(self, j: Journey, tier: str, **fields) -> Row:
        return self.store.create_escalation({"journey_id": j.id, "tier": tier,
                                             "snapshot": snapshot(j), **fields})

    def _close(self, esc: Row) -> None:
        self.store.update_escalation(esc["id"], {"status": "closed", "next_step_at": None,
                                                 "closed_at": self.clock().isoformat()})

    def _later(self, seconds: int) -> str:
        return (self.clock() + timedelta(seconds=seconds)).isoformat()

    def _ask_person(self, j: Journey) -> None:
        esc = self._create(j, "person", next_step_at=self._later(self.settings.checkin_reply_timeout_s))
        acct = self.store.get_google_account()
        if acct and acct.get("google_email"):
            self._send(esc, acct["google_email"], "person_checkin", *self._person_mail(esc["snapshot"]))

    def _start_sequential(self, j: Journey, esc: Row | None) -> None:
        if esc and esc["tier"] in FAMILY_KINDS:
            return  # already emailing family
        if esc:
            esc = self.store.update_escalation(esc["id"], {"tier": "sequential", "next_priority": 1})
        else:
            esc = self._create(j, "sequential", next_priority=1)
        self._email_next(esc)

    def _email_next(self, esc: Row) -> None:
        """Email the next contact by priority; skip ahead past any Gmail failure."""
        start = esc.get("next_priority") or 1
        for c in self.store.list_contacts():
            if c["priority"] < start:
                continue
            if self._send_family(esc, c, "sequential"):
                self.store.update_escalation(esc["id"], {
                    "next_priority": c["priority"] + 1,
                    "next_step_at": self._later(self.settings.escalation_step_s)})
                return
        # Nobody left to email: stop here (the user's rule; no re-send to everyone).
        self.store.update_escalation(esc["id"], {"next_priority": None, "next_step_at": None})

    def _everyone(self, j: Journey, esc: Row | None) -> None:
        if esc:
            esc = self.store.update_escalation(esc["id"], {"tier": "all", "next_step_at": None,
                                                           "snapshot": snapshot(j)})
        else:
            esc = self._create(j, "all")
        for c in self.store.list_contacts():
            self._send_family(esc, c, "all")

    def _update_family(self, esc: Row, snap: dict, kind: str) -> None:
        emailed = []
        for n in self.store.list_notifications(esc["id"]):
            if n["kind"] in FAMILY_KINDS and not n["error"] and n["recipient"] not in emailed:
                emailed.append(n["recipient"])
        for to in emailed:
            contact = self._contact_by_email(to)
            self._send(esc, to, kind, *self._update_mail(snap, kind, contact))

    # ============================================================ sending
    def _send_family(self, esc: Row, contact: Row, kind: str) -> bool:
        token = secrets.token_urlsafe(24)
        subject, text = self._family_mail(esc["snapshot"], contact, kind, token)
        return self._send(esc, contact["email"], kind, subject, text, token=token)

    def _send(self, esc: Row, to: str, kind: str, subject: str, text: str,
              token: str | None = None) -> bool:
        """Claim the (escalation, kind, recipient) slot, then send. False if failed or a duplicate."""
        note = self.store.claim_notification({
            "escalation_id": esc["id"], "journey_id": esc["journey_id"], "recipient": to,
            "kind": kind, "ack_token_hash": hash_token(token) if token else None})
        if not note:
            return False  # this exact email already went out
        try:
            msg_id = self.mailer.send(to, subject, text)
            self.store.update_notification(note["id"], {"gmail_message_id": msg_id})
            return True
        except Exception as e:  # noqa: BLE001 - log it and let the caller move on
            message = e.message if isinstance(e, ApiError) else str(e)
            log.warning("email (%s) failed: %s", kind, type(e).__name__)
            self.store.update_notification(note["id"], {"error": message[:500] or type(e).__name__})
            return False

    def _contact_by_email(self, email: str) -> Row | None:
        return next((c for c in self.store.list_contacts() if c["email"].lower() == email.lower()), None)

    # ============================================================ wording
    @staticmethod
    def _first(snap: dict) -> str:
        return (snap.get("user_name") or "Margaret").split()[0]

    @staticmethod
    def _where(snap: dict) -> str:
        seen = _parse(snap.get("last_seen"))
        clock = seen.astimezone().strftime("%I:%M %p").lstrip("0") if seen else "unknown time"
        return (f"Last known location ({clock}): "
                f"https://www.google.com/maps?q={snap['last_lat']:.6f},{snap['last_lng']:.6f}")

    def _person_mail(self, snap: dict) -> tuple[str, str]:
        name = self._first(snap)
        return (f"Are you okay, {name}?",
                f"Hi {name},\n\nIt looks like you may have left your usual route to "
                f"{snap['destination']}. Are you okay?\n\nPlease answer the question on your phone. "
                f"If you don't, your family will be told so they can help.\n\n— Walk Safety\n\n{DISCLAIMER}")

    def _family_mail(self, snap: dict, contact: Row, kind: str, token: str) -> tuple[str, str]:
        name, full = self._first(snap), snap.get("user_name") or "Margaret"
        hello = f"Hi {contact['name'].split()[0]},"
        why = "; ".join(r.rstrip(".") for r in snap.get("reasons") or []) or "unusual movement"
        if snap.get("help_requested"):
            situation = f"{full} pressed the help button"
        else:
            situation = f"{full} may be lost (risk {snap.get('score', 0)}/100: {why})"
        link = f"{self.settings.public_base_url}/api/escalations/ack?token={token}"
        if kind == "all":
            subject = f"URGENT: {name} needs help now"
            next_step = "Every trusted contact has been emailed at the same time."
        else:
            subject = f"{name} may need help on the way to {snap['destination']}"
            minutes = round(self.settings.escalation_step_s / 60)
            next_step = (f"If nobody responds within {minutes} min, the next contact on the list "
                         f"will be emailed.")
        text = (f"{hello}\n\n{situation} while walking from {snap['start']} to "
                f"{snap['destination']}.\n\n{self._where(snap)}\n\n"
                f"If you are going to help, click \"I'm on it\" so the others aren't emailed:\n{link}\n\n"
                f"{next_step}\n\n— Walk Safety, sent from {name}'s Gmail\n\n{DISCLAIMER}")
        return subject, text

    def _update_mail(self, snap: dict, kind: str, contact: Row | None) -> tuple[str, str]:
        name = self._first(snap)
        hello = f"Hi {contact['name'].split()[0]}," if contact else "Hello,"
        if kind == "arrived":
            subject = f"Update: {name} arrived at {snap['destination']}"
            body = f"{name} has arrived at {snap['destination']}. No further emails will be sent."
        elif kind == "ended":
            subject = f"Update: {name}'s walk was ended in the app"
            body = (f"{name}'s walk was marked as finished in the app, but the last location was "
                    f"not at {snap['destination']}. No further emails will be sent for this alert. "
                    f"Please check on {name} if you haven't heard from anyone.")
        else:
            subject = f"Update: {name} is okay"
            body = (f"{name} answered \"I'm okay\" on the phone. The alert is closed and no "
                    f"further emails will be sent.")
        return subject, f"{hello}\n\n{body}\n\n{self._where(snap)}\n\n— Walk Safety\n\n{DISCLAIMER}"
