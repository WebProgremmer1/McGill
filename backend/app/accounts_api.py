"""Endpoints for setup: connect Google, read one Calendar event, and manage trusted contacts.

Kept in its own router so main.py only needs `app.include_router(...)`.
Everything that exposes account data requires the server-side session created by Connect Google.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from html import escape
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .db import Store
from .errors import ApiError, not_found
from .google_auth import OAUTH_STATE_COOKIE, SCOPES, SESSION_COOKIE, SESSION_TTL_S, STATE_TTL_S, GoogleAuth
from .google_services import CalendarReader, HelpEmailer

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., pattern=EMAIL, max_length=254)
    relationship: str | None = Field(None, max_length=60, examples=["daughter"])
    priority: int = Field(..., ge=1, le=50, description="1 = emailed first.")
    photo_url: str | None = Field(None, max_length=2000)
    source: str = Field("manual", pattern="^(manual|google)$")


class ContactUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    email: str | None = Field(None, pattern=EMAIL, max_length=254)
    relationship: str | None = Field(None, max_length=60)
    priority: int | None = Field(None, ge=1, le=50)
    photo_url: str | None = Field(None, max_length=2000)


class Contact(BaseModel):
    id: str
    name: str
    email: str
    relationship: str | None = None
    priority: int
    photo_url: str | None = None
    source: str = "manual"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContactOrder(BaseModel):
    ids: list[str] = Field(..., description="Every contact id, first-to-email first.")


def session_guard(google: GoogleAuth):
    """A FastAPI dependency that requires the app session created by Connect Google."""
    def require_session(request: Request) -> dict[str, str]:
        session = google.read_session(request.cookies.get(SESSION_COOKIE))
        if not session:
            raise ApiError(401, "session_required", "Connect Google to continue.")
        return session
    return require_session


def build_router(store: Store, google: GoogleAuth, done_url: str, emailer: HelpEmailer,
                 calendar: CalendarReader) -> APIRouter:
    r = APIRouter()
    secure_cookie = google.settings.google_oauth_redirect_uri.startswith("https://")
    require_session = session_guard(google)

    def owned_contact(contact_id: str, session: dict[str, str]) -> dict:
        row = store.get_contact(contact_id)
        if row.get("person_key") != session["person_key"]:
            raise not_found("contact", contact_id)
        return row

    # ------------------------------------------------------------ Google
    @r.get("/api/google/connect", tags=["google"])
    def google_connect(person_name: str | None = None, redirect: bool = True):
        """Open this in a browser to connect the approved Google account.
        `?redirect=false` returns the consent URL as JSON instead (for a frontend button)."""
        url = google.start(person_name)
        state = parse_qs(urlparse(url).query)["state"][0]
        response = RedirectResponse(url) if redirect else JSONResponse({"auth_url": url})
        response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=STATE_TTL_S, httponly=True,
                            samesite="lax", secure=secure_cookie, path="/api/google")
        return response

    @r.get("/api/google/callback", tags=["google"], include_in_schema=False)
    def google_callback(request: Request, state: str | None = None, code: str | None = None,
                        error: str | None = None):
        # The browser that finishes sign-in must be the browser that started it.
        expected = request.cookies.get(OAUTH_STATE_COOKIE, "")
        if state and not secrets.compare_digest(expected.encode(), state.encode()):
            state = None
        try:
            status = google.finish(state, code, error)
        except ApiError as e:
            response = HTMLResponse(_page("Google wasn't connected", escape(e.message), ok=False),
                                    status_code=e.status_code)
            response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/google")
            return response
        if done_url:
            response = RedirectResponse(f"{done_url}{'&' if '?' in done_url else '?'}google=connected")
        else:
            missing = status.get("missing_scopes") or []
            note = ("" if not missing else
                    "<p><b>Some permissions were not ticked:</b> " + ", ".join(escape(m.rsplit('/', 1)[-1]) for m in missing)
                    + ". Connect again and allow all of them.</p>")
            response = HTMLResponse(_page("Google connected",
                                          f"Connected as <b>{escape(status.get('google_email') or '')}</b>. "
                                          f"You can close this tab.{note}", ok=not missing))
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/google")
        response.set_cookie(SESSION_COOKIE, google.issue_session(), max_age=SESSION_TTL_S, httponly=True,
                            samesite="lax", secure=secure_cookie, path="/")
        return response

    @r.get("/api/google/status", tags=["google"])
    def google_status(request: Request, check: bool = False):
        """Without a session this reveals only whether sign-in is configured."""
        session = google.read_session(request.cookies.get(SESSION_COOKIE))
        if not session:
            return {"configured": google.configured, "problem": google.problem,
                    "connected": False, "required_scopes": SCOPES}
        return {**google.status(session["person_key"], check=check),
                "help_email_to": emailer.recipient,
                "help_email_consent": emailer.settings.help_email_consent,
                "help_email_ready": emailer.problem(session) is None,
                "help_email_problem": emailer.problem(session),
                "calendar_configured": bool(calendar.settings.google_calendar_id)}

    @r.get("/api/google/calendar/next", tags=["google"])
    def google_calendar_next(request: Request):
        """The next event's title and start time, for the signed-in account only."""
        session = google.read_session(request.cookies.get(SESSION_COOKIE))
        return calendar.next_event(session) if session else {"state": "not_connected"}

    @r.post("/api/google/disconnect", tags=["google"])
    def google_disconnect(session: dict[str, str] = Depends(require_session)):
        google.disconnect(session["person_key"])
        response = JSONResponse({"connected": False})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    # ------------------------------------------------------------ trusted contacts
    @r.get("/api/contacts", response_model=list[Contact], tags=["contacts"])
    def list_contacts(session: dict[str, str] = Depends(require_session)):
        """Trusted contacts, in the order they get emailed."""
        return store.list_contacts(session["person_key"])

    @r.post("/api/contacts", response_model=Contact, status_code=201, tags=["contacts"])
    def create_contact(body: ContactCreate, session: dict[str, str] = Depends(require_session)):
        return store.create_contact({**body.model_dump(), "person_key": session["person_key"]})

    # Declared before /{contact_id} routes so "order" is never treated as an ID.
    @r.put("/api/contacts/order", response_model=list[Contact], tags=["contacts"])
    def reorder_contacts(body: ContactOrder, session: dict[str, str] = Depends(require_session)):
        """Set priorities 1..n in the order given."""
        return store.reorder_contacts(body.ids, session["person_key"])

    @r.get("/api/contacts/{contact_id}", response_model=Contact, tags=["contacts"])
    def get_contact(contact_id: str, session: dict[str, str] = Depends(require_session)):
        return owned_contact(contact_id, session)

    @r.patch("/api/contacts/{contact_id}", response_model=Contact, tags=["contacts"])
    def update_contact(contact_id: str, body: ContactUpdate, session: dict[str, str] = Depends(require_session)):
        current = owned_contact(contact_id, session)
        fields = body.model_dump(exclude_unset=True)
        return store.update_contact(contact_id, fields) if fields else current

    @r.delete("/api/contacts/{contact_id}", status_code=204, tags=["contacts"])
    def delete_contact(contact_id: str, session: dict[str, str] = Depends(require_session)):
        owned_contact(contact_id, session)
        store.delete_contact(contact_id)

    return r


def _page(title: str, body: str, ok: bool) -> str:
    """`body` is trusted HTML. Callers must escape anything that came from a request."""
    color = "#1a7f37" if ok else "#b42318"
    return f"""<!doctype html><meta charset="utf-8"><title>{escape(title)}</title>
<body style="font:16px system-ui;max-width:520px;margin:15vh auto;padding:0 16px">
<h1 style="color:{color};font-size:24px">{escape(title)}</h1><p>{body}</p></body>"""
