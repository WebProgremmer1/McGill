"""FastAPI app. Start with:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .demo import run_demo
from .errors import ApiError
from .events import EVENT_TYPES, EventBus, sse_stream
from .models import (
    DISCLAIMER, Alert, AnalyzeRequest, CheckIn, CheckInRequest, CheckInResult,
    ExpectedRouteRequest, Journey, JourneyCreate, LocationResult, LocationUpdate,
    Place, TrackPoint,
)
from .risk import DEFAULT_CONFIG, RiskConfig, evaluate
from .routes_provider import PREDEFINED_ROUTES, RouteProvider
from .service import JourneyService


def create_app(
    settings: Settings | None = None,
    route_provider: RouteProvider | None = None,
    risk_config: RiskConfig = DEFAULT_CONFIG,
) -> FastAPI:
    settings = settings or Settings.from_env()
    service = JourneyService(
        route_provider or RouteProvider(settings), risk_config, EventBus(),
        no_signal_after=timedelta(seconds=settings.no_signal_after_s or 300),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = None
        if settings.no_signal_after_s > 0:
            task = asyncio.create_task(_watchdog(service, settings.watchdog_interval_s))
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

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
            "no_signal_after_s": settings.no_signal_after_s,
            "live_subscribers": service.events.subscriber_count,
            "disclaimer": DISCLAIMER,
        }

    @app.get("/api/maps-config", tags=["system"])
    def maps_config():
        """Settings for the live map page. The browser key is meant to be public
        (Maps JavaScript keys always reach the browser); restrict it by referrer."""
        return {
            "browser_key": settings.google_browser_key,
            "maps_enabled": bool(settings.google_browser_key),
            "routes_enabled": settings.google_enabled,
            "default_center": {"latitude": 45.5019, "longitude": -73.5674},
            "city": "Montreal",
        }

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

    @app.get("/api/events", tags=["alerts"], response_class=StreamingResponse)
    async def events(
        request: Request,
        journey_id: str | None = None,
        types: str | None = Query(None, description="Comma-separated event types, e.g. alert_created,alert_resolved"),
        last_event_id: int | None = Header(None, alias="Last-Event-ID"),
    ):
        """Live stream (Server-Sent Events). Open it with `new EventSource(url)`.
        Event types: """ + ", ".join(EVENT_TYPES) + """. Each event's data is
        `{id, type, journey_id, sent_at, data}`."""
        wanted = None
        if types:
            wanted = frozenset(t.strip() for t in types.split(",") if t.strip())
            unknown = sorted(wanted - set(EVENT_TYPES))
            if unknown:
                raise ApiError(422, "unknown_event_type", f"Unknown event types: {', '.join(unknown)}.",
                               {"available": list(EVENT_TYPES)})
        stream = sse_stream(service.events, request.is_disconnected, journey_id=journey_id,
                            types=wanted, last_event_id=last_event_id)
        return StreamingResponse(stream, media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/alerts/{alert_id}/acknowledge", response_model=Alert, tags=["alerts"])
    def acknowledge(alert_id: str):
        return service.acknowledge(alert_id)

    # ------------------------------------------------------------ stateless helpers
    @app.post("/api/expected-route", tags=["stateless"])
    def expected_route(body: ExpectedRouteRequest):
        """Look up a walking route once (Google Routes, or a straight-line fallback)."""
        r = service.routes.resolve(
            Place(name="start", **body.start.model_dump()),
            Place(name="destination", **body.destination.model_dump()), None, None)
        return {"route": r.points, "route_source": r.source, "route_warning": r.warning,
                "distance_m": r.distance_m, "duration_s": r.duration_s}

    @app.post("/api/analyze-journey", tags=["stateless"])
    def analyze_journey(body: AnalyzeRequest):
        """Score a whole GPS history without creating a journey. Nothing is stored.
        Same engine and thresholds as POST /api/journeys/{id}/location."""
        track = [TrackPoint(latitude=r.latitude, longitude=r.longitude, timestamp=r.timestamp,
                            accuracy_m=r.accuracy_meters) for r in body.gps_history]
        for prev, cur in zip(track, track[1:]):
            if cur.timestamp < prev.timestamp:
                raise ApiError(422, "out_of_order_timestamp",
                               "gps_history must be sorted by timestamp (oldest first).",
                               {"at": cur.timestamp.isoformat()})
        if body.now is not None and track and body.now < track[-1].timestamp:
            raise ApiError(422, "invalid_now", "now cannot be earlier than the last GPS reading.")
        route = body.expected_route
        risk = evaluate(
            track=track, route=route, start=route[0],
            destination=body.destination or route[-1],
            expected_arrival=body.expected_arrival, safe_zones=body.safe_zones,
            started_at=body.started_at, expected_duration_s=body.expected_duration_s,
            now=body.now, cfg=service.risk_config,
        )
        return {"journey_id": body.journey_id, "risk": risk}

    @app.post("/api/demo/run", tags=["demo"])
    def demo_run():
        """Replay the whole Tim Hortons scenario instantly. The journey, check-in and
        alert it creates are visible through the normal GET endpoints afterwards."""
        return run_demo(service)

    @app.post("/api/demo/reset", tags=["demo"])
    def demo_reset():
        service.reset()
        return {"status": "reset"}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/viewer/live-map.html")

    app.mount("/viewer", StaticFiles(directory=Path(__file__).resolve().parent.parent / "viewer", html=True), name="viewer")

    return app


log = logging.getLogger("watchdog")


async def _watchdog(service: JourneyService, interval_s: float) -> None:
    """Background loop: raise no_signal alerts for journeys whose phone went quiet."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            for alert in service.check_silence():
                log.warning("no_signal alert %s for journey %s", alert.id, alert.journey_id)
        except Exception:  # noqa: BLE001 - never let the watchdog die
            log.exception("no-signal watchdog failed")


app = create_app()
