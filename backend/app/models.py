"""Pydantic models: API requests/responses and the in-memory journey state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator

DISCLAIMER = (
    "Experimental navigation-risk heuristics for a hackathon prototype. "
    "Not medically validated and not for real emergency monitoring."
)

RiskLevel = Literal["low", "medium", "high"]
RecommendedAction = Literal[
    "continue_monitoring",
    "contextual_check_in",
    "caregiver_alert",
    "immediate_caregiver_alert",
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def to_utc(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC; convert aware ones to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- geometry
class Coordinates(BaseModel):
    latitude: float = Field(..., ge=-90, le=90, examples=[45.5048])
    longitude: float = Field(..., ge=-180, le=180, examples=[-73.5772])


class Place(Coordinates):
    name: str = Field(..., min_length=1, max_length=120, examples=["Tim Hortons"])


class SafeZone(Coordinates):
    name: str = Field(..., min_length=1, max_length=120, examples=["Tim Hortons"])
    radius_m: float = Field(..., gt=0, le=50_000, examples=[75])


class TrackPoint(Coordinates):
    timestamp: datetime


# ---------------------------------------------------------------- requests
class JourneyCreate(BaseModel):
    user_name: str = Field("Margaret", min_length=1, max_length=80)
    start: Place
    destination: Place
    expected_arrival: datetime
    route: list[Coordinates] | None = Field(
        None, min_length=2, description="Optional route polyline supplied by the client."
    )
    predefined_route: str | None = Field(
        None, description="Name of an offline route, e.g. 'tim_hortons_demo'."
    )
    fallback_route: str | None = Field(
        None, description="Offline route to use if Google Routes cannot provide a walking route."
    )
    safe_zones: list[SafeZone] = Field(default_factory=list)
    started_at: datetime | None = Field(
        None, description="Journey start time. Defaults to now; set it for simulations."
    )

    @field_validator("expected_arrival", "started_at")
    @classmethod
    def _utc(cls, v):
        return to_utc(v) if v is not None else v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_name": "Margaret",
                    "start": {"name": "Home", "latitude": 45.5048, "longitude": -73.5772},
                    "destination": {"name": "Tim Hortons", "latitude": 45.5088, "longitude": -73.5697},
                    "expected_arrival": "2026-01-01T09:15:00Z",
                    "predefined_route": "tim_hortons_demo",
                    "safe_zones": [
                        {"name": "Home", "latitude": 45.5048, "longitude": -73.5772, "radius_m": 75},
                        {"name": "Tim Hortons", "latitude": 45.5088, "longitude": -73.5697, "radius_m": 75},
                    ],
                }
            ]
        }
    }


class LocationUpdate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    timestamp: datetime | None = Field(None, description="Defaults to server time if omitted.")

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, v):
        return to_utc(v) if v is not None else v

    model_config = {
        "json_schema_extra": {
            "examples": [{"latitude": 45.5060, "longitude": -73.5754, "timestamp": "2026-01-01T09:01:00Z"}]
        }
    }


class RouteRequest(BaseModel):
    start: Coordinates
    destination: Coordinates


class CheckInRequest(BaseModel):
    help_requested: bool = Field(False, description="True = the user pressed the help button.")
    response: str | None = Field(None, max_length=300, description="The user's answer to a check-in.")
    checkin_id: str | None = Field(None, description="Which check-in is being answered (default: latest open).")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"help_requested": False, "response": "I'm okay"},
                {"help_requested": True},
            ]
        }
    }


# ---------------------------------------------------------------- demo messages
class MessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=280, examples=["I got home safely."])

    model_config = {"str_strip_whitespace": True}


class Message(BaseModel):
    """An ordinary note to a caregiver. It is never an alert or a journey."""
    id: str = Field(default_factory=lambda: new_id("msg"))
    body: str
    created_at: datetime


# ---------------------------------------------------------------- risk
class RiskReason(BaseModel):
    code: Literal["off_route", "stationary", "repeated_revisits", "left_safe_zone", "taking_too_long",
                  "ignored_checkin", "said_okay"]
    points: int
    description: str


class RiskAssessment(BaseModel):
    score: int = Field(..., ge=0, le=100)
    level: RiskLevel
    reasons: list[RiskReason]
    recommended_action: RecommendedAction
    help_requested: bool = False
    evaluated_at: datetime
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------- escalation outputs
class CheckIn(BaseModel):
    id: str = Field(default_factory=lambda: new_id("chk"))
    journey_id: str
    created_at: datetime
    status: Literal["open", "answered", "closed"] = "open"
    message: str
    options: list[str]
    risk_score: int
    reason_codes: list[str]
    response: str | None = None
    answered_at: datetime | None = None


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: new_id("alt"))
    journey_id: str
    user_name: str
    type: Literal["risk", "help_request", "said_okay"]
    priority: Literal["info", "high", "critical"]
    message: str
    risk_score: int
    risk_level: RiskLevel
    reasons: list[RiskReason]
    location: TrackPoint | None = None
    created_at: datetime
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    # "accepted" means Gmail's API accepted the message. It does not prove inbox delivery.
    email_status: Literal["not_sent", "sending", "accepted", "failed"] = "not_sent"


# ---------------------------------------------------------------- journey
class Journey(BaseModel):
    id: str = Field(default_factory=lambda: new_id("jrn"))
    user_name: str
    status: Literal["active", "completed", "cancelled"] = "active"
    start: Place
    destination: Place
    expected_arrival: datetime
    started_at: datetime
    ended_at: datetime | None = None
    route: list[Coordinates]
    route_source: Literal["client", "predefined", "google_routes", "fallback_straight_line"]
    route_warning: str | None = None
    route_distance_m: float | None = None
    route_duration_s: int | None = None
    safe_zones: list[SafeZone] = Field(default_factory=list)
    track: list[TrackPoint] = Field(default_factory=list)
    help_requested: bool = False
    risk: RiskAssessment

    # internal bookkeeping (not sent to clients)
    high_alert_latched: bool = Field(False, exclude=True)
    critical_latched: bool = Field(False, exclude=True)  # 90+ "email everyone" already sent
    email_escalation: bool = Field(False, exclude=True)  # only walks started with the app session can email
    last_checkin_at: datetime | None = Field(None, exclude=True)
    okay_at: datetime | None = Field(None, exclude=True)  # when she answered "I'm okay"
    checkin_sent_at: datetime | None = Field(None, exclude=True)  # unanswered check-in: when it was sent
    checkin_sent_where: TrackPoint | None = Field(None, exclude=True)  # ...and where she was

    @computed_field  # type: ignore[misc]
    @property
    def latest_location(self) -> TrackPoint | None:
        return self.track[-1] if self.track else None

    def reference_time(self) -> datetime:
        """The journey's 'now': the newest GPS timestamp (or its start).
        Using GPS time instead of the wall clock lets simulations replay instantly."""
        return self.track[-1].timestamp if self.track else self.started_at


class LocationResult(BaseModel):
    journey_id: str
    journey_status: str
    location: TrackPoint
    risk: RiskAssessment
    checkin_created: CheckIn | None = None
    alert_created: Alert | None = None
    deduplicated: bool = False


class CheckInResult(BaseModel):
    journey_id: str
    risk: RiskAssessment
    checkin: CheckIn | None = None
    alert: Alert | None = None
    deduplicated: bool = False


MIN = timedelta(minutes=1)
