"""Sending email from the person's own Gmail (gmail.send scope only; Gmail is never read).

`Mailer` is the interface the escalation engine uses. Tests pass a fake with the same
`send()` method, so nothing here runs offline.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Protocol

from .errors import ApiError
from .google_auth import GoogleAuth
from .google_services import GmailSender, gmail_send


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str, html: str | None = None) -> str:
        """Send one email. Returns the provider's message id; raises on failure."""
        ...


class GmailMailer:
    def __init__(self, google: GoogleAuth, sender: GmailSender | None = None):
        self.google = google
        self._send = sender or gmail_send

    def ready(self) -> bool:
        return self.google.approved_account() is not None

    def sender(self) -> str | None:
        acct = self.google.store.get_google_account()
        return acct["google_email"] if acct else None

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> str:
        if not self.ready():
            raise ApiError(403, "google_account_not_allowed", "This Google account isn't approved for this demo.")
        creds = self.google.credentials()  # raises google_not_connected / not_configured
        msg = EmailMessage()
        msg["To"] = to
        if self.sender():
            msg["From"] = self.sender()
        msg["Subject"] = subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return self._send(creds, raw)
