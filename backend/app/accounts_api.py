"""Endpoints for setup: connect Google, and manage trusted contacts.

Kept in its own router so main.py only needs `app.include_router(...)`.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .db import Store
from .errors import ApiError
from .google_auth import GoogleAuth

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


def build_router(store: Store, google: GoogleAuth, done_url: str) -> APIRouter:
    r = APIRouter()

    # ------------------------------------------------------------ Google
    @r.get("/api/google/connect", tags=["google"])
    def google_connect(person_name: str | None = None, redirect: bool = True):
        """Open this in a browser to connect the person's Google account.
        `?redirect=false` returns the consent URL as JSON instead (for a frontend button)."""
        url = google.start(person_name)
        return RedirectResponse(url) if redirect else {"auth_url": url}

    @r.get("/api/google/callback", tags=["google"], include_in_schema=False)
    def google_callback(request: Request, state: str | None = None, code: str | None = None,
                        error: str | None = None):
        try:
            status = google.finish(state, code, error)
        except ApiError as e:
            return HTMLResponse(_page("Google wasn't connected", e.message, ok=False), status_code=e.status_code)
        if done_url:
            return RedirectResponse(f"{done_url}{'&' if '?' in done_url else '?'}google=connected")
        missing = status.get("missing_scopes") or []
        note = ("" if not missing else
                "<p><b>Some permissions were not ticked:</b> " + ", ".join(escape(m.rsplit('/', 1)[-1]) for m in missing)
                + ". Connect again and allow all of them.</p>")
        return HTMLResponse(_page("Google connected",
                                  f"Connected as <b>{escape(status.get('google_email') or '')}</b>. "
                                  f"You can close this tab.{note}", ok=not missing))

    @r.get("/api/google/status", tags=["google"])
    def google_status(check: bool = False):
        """Is Google connected? `?check=true` also asks Google whether the token still works."""
        return google.status(check=check)

    @r.post("/api/google/disconnect", tags=["google"])
    def google_disconnect():
        google.disconnect()
        return {"connected": False}

    @r.get("/api/google/contacts", tags=["google"])
    def google_contacts(q: str = ""):
        """Search the person's Google Contacts (for picking trusted contacts)."""
        return {"contacts": google.search_contacts(q)}

    # ------------------------------------------------------------ trusted contacts
    @r.get("/api/contacts", response_model=list[Contact], tags=["contacts"])
    def list_contacts():
        """Trusted contacts, in the order they get emailed."""
        return store.list_contacts()

    @r.post("/api/contacts", response_model=Contact, status_code=201, tags=["contacts"])
    def create_contact(body: ContactCreate):
        return store.create_contact(body.model_dump())

    @r.get("/api/contacts/{contact_id}", response_model=Contact, tags=["contacts"])
    def get_contact(contact_id: str):
        return store.get_contact(contact_id)

    @r.patch("/api/contacts/{contact_id}", response_model=Contact, tags=["contacts"])
    def update_contact(contact_id: str, body: ContactUpdate):
        fields = body.model_dump(exclude_unset=True)
        return store.update_contact(contact_id, fields) if fields else store.get_contact(contact_id)

    @r.delete("/api/contacts/{contact_id}", status_code=204, tags=["contacts"])
    def delete_contact(contact_id: str):
        store.delete_contact(contact_id)

    @r.put("/api/contacts/order", response_model=list[Contact], tags=["contacts"])
    def reorder_contacts(body: ContactOrder):
        """Set priorities 1..n in the order given."""
        return store.reorder_contacts(body.ids)

    return r


def _page(title: str, body: str, ok: bool) -> str:
    color = "#1a7f37" if ok else "#b42318"
    return f"""<!doctype html><meta charset="utf-8"><title>{escape(title)}</title>
<body style="font:16px system-ui;max-width:520px;margin:15vh auto;padding:0 16px">
<h1 style="color:{color};font-size:24px">{escape(title)}</h1><p>{body}</p></body>"""
