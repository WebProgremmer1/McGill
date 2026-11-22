"""FastAPI app. Start with:  uvicorn app.main:app --reload"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .accounts_api import build_router
from .config import Settings
from .db import Store, create_store
from .demo import run_demo
from .errors import ApiError
from .event_emails import EventEmails
from .escalation import EscalationEngine
from .escalation_api import build_router as build_escalation_router, start_ticker
from .google_auth import GoogleAuth
from .mailer import GmailMailer
from .reminders import VisitReminders
from .models import (
    DISCLAIMER, Alert, CheckIn, CheckInRequest, CheckInResult, Journey,
    JourneyCreate, LocationResult, LocationUpdate, Place, RouteRequest,
)
from .routes_provider import PREDEFINED_ROUTES, RouteProvider
from .service import JourneyService


def create_app(settings: Settings | None = None, route_provider: RouteProvider | None = None,
               store: Store | None = None, google: GoogleAuth | None = None,
               escalation: EscalationEngine | None = None,
               reminders: VisitReminders | None = None,
               event_emails: EventEmails | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or create_store(settings)
    google = google or GoogleAuth(settings, store)
    mailer = GmailMailer(google)
    engine = escalation or EscalationEngine(store, mailer, settings)
    service = JourneyService(route_provider or RouteProvider(settings), engine)
    reminders = reminders or VisitReminders(store, settings, google=google)
    event_emails = event_emails or EventEmails(store, mailer, reminders, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # 3-min / 5-min escalation steps, and calendar event emails 20 min before each event
        stop = start_ticker([engine, event_emails], settings.escalation_tick_s)
        yield
        stop.set()

    app = FastAPI(
        title="Cognitive Safety Backend (hackathon prototype)",
        version="0.1.0",
        description=DISCLAIMER + " Uses fictional users and synthetic data only.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.state.service = service
    app.state.store = store
    app.state.google = google
    app.state.escalation = engine

    # ------------------------------------------------------------ errors
    def err(status: int, code: str, message: str, details=None) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return err(e.status_code, e.code, e.message, e.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in x["loc"][1:]), "message": x["msg"]}
            for x in e.errors()
        ]
        return err(422, "validation_error", "Request body failed validation.", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        return err(e.status_code, "http_error", str(e.detail))

    # ------------------------------------------------------------ routes
    @app.get("/api/health", tags=["system"])
    def health():
        return {
            "status": "ok",
            "google_routes_configured": settings.google_enabled,
            "route_mode": settings.route_mode,
            "database": store.kind,
            "database_ok": store.ping(),
            "google_oauth_configured": google.configured,
            "disclaimer": DISCLAIMER,
        }

    @app.get("/api/maps-config", tags=["live map"])
    def maps_config():
        """The Google key for the live map page. A Maps JavaScript key always ends up
        in the browser, so restrict it to http://localhost:8000/* in Google Cloud."""
        return {"browser_key": settings.google_browser_key,
                "maps_enabled": bool(settings.google_browser_key)}

    @app.post("/api/expected-route", tags=["live map"])
    def expected_route(body: RouteRequest):
        """Look up the walking route between two points (Google, or a straight line)."""
        start = Place(name="start", latitude=body.start.latitude, longitude=body.start.longitude)
        dest = Place(name="destination", latitude=body.destination.latitude, longitude=body.destination.longitude)
        r = service.routes.resolve(start, dest, None, None)
        return {"route": r.points, "route_source": r.source, "route_warning": r.warning,
                "distance_m": r.distance_m, "duration_s": r.duration_s}

    @app.get("/api/routes/predefined", tags=["system"])
    def predefined_routes():
        return {"routes": sorted(PREDEFINED_ROUTES)}

    @app.post("/api/journeys", response_model=Journey, status_code=201, tags=["journeys"])
    def create_journey(body: JourneyCreate):
        return service.create_journey(body)

    @app.get("/api/journeys", response_model=list[Journey], tags=["journeys"])
    def list_journeys():
        return list(service.journeys.values())

    @app.get("/api/journeys/{journey_id}", response_model=Journey, tags=["journeys"])
    def get_journey(journey_id: str):
        return service.get(journey_id)

    @app.post("/api/journeys/{journey_id}/location", response_model=LocationResult, tags=["journeys"])
    def post_location(journey_id: str, body: LocationUpdate):
        return service.add_location(journey_id, body)

    @app.get("/api/journeys/{journey_id}/checkins", response_model=list[CheckIn], tags=["check-ins"])
    def get_checkins(journey_id: str):
        return service.journey_checkins(journey_id)

    @app.post("/api/journeys/{journey_id}/checkin", response_model=CheckInResult, tags=["check-ins"])
    def post_checkin(journey_id: str, body: CheckInRequest):
        return service.checkin(journey_id, body)

    @app.post("/api/journeys/{journey_id}/complete", response_model=Journey, tags=["journeys"])
    def complete(journey_id: str):
        return service.complete(journey_id)

    @app.post("/api/journeys/{journey_id}/cancel", response_model=Journey, tags=["journeys"])
    def cancel(journey_id: str):
        return service.cancel(journey_id)

    @app.get("/api/alerts", response_model=list[Alert], tags=["alerts"])
    def list_alerts(journey_id: str | None = None, acknowledged: bool | None = None):
        return service.list_alerts(journey_id, acknowledged)

    @app.post("/api/alerts/{alert_id}/acknowledge", response_model=Alert, tags=["alerts"])
    def acknowledge(alert_id: str):
        return service.acknowledge(alert_id)

    @app.post("/api/demo/run", tags=["demo"])
    def demo_run():
        """Replay the whole Tim Hortons scenario instantly. The journey, check-in and
        alert it creates are visible through the normal GET endpoints afterwards."""
        return run_demo(service)

    @app.post("/api/demo/reset", tags=["demo"])
    def demo_reset():
        service.reset()
        return {"status": "reset"}

    app.include_router(build_router(store, google, settings.google_oauth_done_url))
    app.include_router(build_escalation_router(engine, service))

    @app.get("/api/reminders", tags=["reminders"])
    def visit_reminders():
        """Visits from Google Calendar in the next 24 h. `show_now` = put it on the phone."""
        return reminders.list()

    @app.post("/api/reminders/email-now", tags=["reminders"])
    def email_calendar_events_now():
        """Send any calendar event emails that are due now (the background timer also does this)."""
        return {"sent": event_emails.tick()}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/viewer/live-map.html")

    app.mount("/viewer", StaticFiles(directory=Path(__file__).resolve().parent.parent / "viewer", html=True), name="viewer")

    return app


app = create_app()
