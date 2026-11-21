"""FastAPI app. Start with:  uvicorn app.main:app --reload"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .demo import run_demo
from .errors import ApiError
from .models import (
    DISCLAIMER, Alert, CheckIn, CheckInRequest, CheckInResult, Journey,
    JourneyCreate, LocationResult, LocationUpdate, Message, MessageCreate, Place, RouteRequest,
)
from .routes_provider import PREDEFINED_ROUTES, RouteProvider
from .service import JourneyService


def create_app(settings: Settings | None = None, route_provider: RouteProvider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = JourneyService(route_provider or RouteProvider(settings))

    app = FastAPI(
        title="Cognitive Safety Backend (hackathon prototype)",
        version="0.1.0",
        description=DISCLAIMER + " Uses fictional users and synthetic data only.",
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
            "disclaimer": DISCLAIMER,
        }

    @app.get("/api/maps-config", tags=["live map"])
    def maps_config():
        """The separate browser key for the map. The server key is never returned.
        Restrict this key to every website origin that serves the map."""
        key = settings.public_browser_key
        return {"browser_key": key, "maps_enabled": bool(key)}

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

    @app.get("/api/messages", response_model=list[Message], tags=["messages"])
    def list_messages():
        return service.list_messages()

    @app.post("/api/messages", response_model=Message, status_code=201, tags=["messages"])
    def create_message(body: MessageCreate):
        return service.add_message(body)

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


app = create_app()
