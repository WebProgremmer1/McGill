"""Endpoints for email escalation: the "I'm on it" link, and a read-only view for the dashboard."""
from __future__ import annotations

import threading
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .errors import ApiError
from .escalation import EscalationEngine
from .service import JourneyService


def _page(title: str, body: str, ok: bool = True, status: int = 200) -> HTMLResponse:
    color = "#1a7f37" if ok else "#b42318"
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<body style="font:18px system-ui;max-width:520px;margin:12vh auto;padding:0 16px;line-height:1.5">
<h1 style="color:{color};font-size:26px">{escape(title)}</h1>{body}</body>""", status_code=status)


def build_router(engine: EscalationEngine, service: JourneyService) -> APIRouter:
    r = APIRouter()

    @r.get("/api/escalations/ack", tags=["escalations"], include_in_schema=False)
    def ack_page(token: str = ""):
        """The link inside the email. A GET only shows a button, so email link scanners
        that open every link can't stop the escalation by accident."""
        if not engine.store.find_notification_by_token(_hash(token)):
            return _page("Link not recognised", "<p>This link is not valid.</p>", ok=False, status=404)
        return _page("Are you going to help?",
                     "<p>Clicking the button tells the others they don't need to be emailed.</p>"
                     f'<form method="post" action="/api/escalations/ack?token={escape(token)}">'
                     '<button style="font:inherit;font-size:20px;padding:14px 28px;border-radius:10px;'
                     'border:0;background:#1a7f37;color:#fff;cursor:pointer">I\'m on it</button></form>')

    @r.post("/api/escalations/ack", tags=["escalations"], include_in_schema=False)
    def ack(token: str = ""):
        try:
            esc, contact = engine.acknowledge(token)
        except ApiError:
            return _page("Link not recognised", "<p>This link is not valid.</p>", ok=False, status=404)
        service.acknowledge_journey_alerts(esc["journey_id"])
        who = escape(contact["name"].split()[0]) if contact else "there"
        name = escape((esc.get("snapshot") or {}).get("user_name") or "them")
        return _page(f"Thank you, {who}",
                     f"<p>The others won't be emailed. Please go and help {name} now.</p>")

    @r.get("/api/escalations", tags=["escalations"])
    def list_escalations(status: str | None = None, journey_id: str | None = None):
        """Email escalations, newest first."""
        return engine.store.list_escalations(status=status, journey_id=journey_id)

    @r.get("/api/escalations/{escalation_id}", tags=["escalations"])
    def get_escalation(escalation_id: str):
        """One escalation and every email it sent (ack tokens are never returned)."""
        esc = engine.store.get_escalation(escalation_id)
        notes = [{k: v for k, v in n.items() if k != "ack_token_hash"}
                 for n in engine.store.list_notifications(escalation_id)]
        return {**esc, "notifications": notes}

    @r.post("/api/escalations/tick", tags=["escalations"])
    def tick():
        """Run the timer now (the background thread also does this every ESCALATION_TICK_S)."""
        return {"advanced": engine.tick()}

    return r


def _hash(token: str) -> str:
    from .escalation import hash_token
    return hash_token(token or "")


def start_ticker(jobs, every_s: int) -> threading.Event:
    """Background thread that runs each job's tick() (escalation steps, calendar emails)
    every `every_s` seconds. Set the returned event to stop it."""
    import logging
    stop = threading.Event()
    log = logging.getLogger(__name__)

    def loop():
        while not stop.wait(every_s):
            for job in jobs:
                try:
                    job.tick()
                except Exception:  # noqa: BLE001 - one failing job must not stop the others
                    log.exception("background %s failed", type(job).__name__)

    threading.Thread(target=loop, name="escalation-ticker", daemon=True).start()
    return stop
