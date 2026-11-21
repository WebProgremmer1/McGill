"""Journey logic + escalation (check-ins and caregiver alerts). In-memory storage."""
from __future__ import annotations

import functools
import threading
from datetime import datetime, timedelta, timezone

from .errors import ApiError, not_found
from .events import EventBus
from .models import (
    Alert, CheckIn, CheckInRequest, CheckInResult, Journey, JourneyCreate,
    LocationResult, LocationUpdate, RiskAssessment, TrackPoint, MIN,
)
from .risk import DEFAULT_CONFIG, RiskConfig, assess
from .routes_provider import RouteProvider

CHECKIN_COOLDOWN = 10 * MIN  # journey-time gap between automatic check-ins
CHECKIN_OPTIONS = ["I'm okay", "Show me the way", "I need help"]
DEFAULT_NO_SIGNAL_AFTER = timedelta(minutes=5)


def _locked(method):
    """Serialise state changes: endpoints run in a thread pool and the no-signal
    watchdog runs on the event loop, so they can touch the same journey."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _duration(d: timedelta) -> str:
    secs = d.total_seconds()
    if secs < 90:
        return f"{secs:.0f} seconds"
    return f"{secs / 60:.0f} minutes"


def _first_name(j: Journey) -> str:
    return j.user_name.split()[0]


def _checkin_message(j: Journey, risk: RiskAssessment) -> str:
    name, dest = _first_name(j), j.destination.name
    codes = [r.code for r in risk.reasons]
    if "off_route" in codes and risk.heading == "away":
        tail = f"It looks like you may be heading away from {dest}. Are you okay? Would you like help finding the way?"
    elif "off_route" in codes and risk.heading == "stopped":
        tail = "You've stopped away from the usual route. Is everything alright? Would you like help finding the way?"
    elif "off_route" in codes:
        tail = "It looks like you may have taken a different way. Are you okay? Would you like help finding the route?"
    elif "repeated_revisits" in codes:
        tail = "It seems you've passed through some of the same places. Would you like some help getting there?"
    elif "stationary" in codes:
        tail = "You've stopped for a while. Is everything alright?"
    elif "late_arrival" in codes:
        tail = "The trip is taking longer than expected. Would you like some help?"
    else:
        tail = "You've gone a bit farther than usual. Are you okay?"
    return f"Hi {name}, you're on your way to {dest}. {tail}"


class JourneyService:
    def __init__(
        self,
        route_provider: RouteProvider,
        risk_config: RiskConfig = DEFAULT_CONFIG,
        events: EventBus | None = None,
        no_signal_after: timedelta = DEFAULT_NO_SIGNAL_AFTER,
    ):
        self.routes = route_provider
        self.risk_config = risk_config
        self.events = events or EventBus()
        self.no_signal_after = no_signal_after
        self._lock = threading.RLock()
        self.journeys: dict[str, Journey] = {}
        self.checkins: dict[str, CheckIn] = {}
        self.alerts: dict[str, Alert] = {}

    @_locked
    def reset(self) -> None:
        self.journeys.clear()
        self.checkins.clear()
        self.alerts.clear()

    # ---------------------------------------------------------- journeys
    def create_journey(self, req: JourneyCreate) -> Journey:
        started = req.started_at or _now()
        route = self.routes.resolve(req.start, req.destination, req.route, req.predefined_route)
        j = Journey(
            user_name=req.user_name,
            start=req.start,
            destination=req.destination,
            expected_arrival=req.expected_arrival,
            started_at=started,
            route=route.points,
            route_source=route.source,  # type: ignore[arg-type]
            route_warning=route.warning,
            route_distance_m=route.distance_m,
            route_duration_s=route.duration_s,
            safe_zones=req.safe_zones,
            signal_watch=req.signal_watch,
            last_seen_at=_now(),
            risk=RiskAssessment(
                score=0, level="low", reasons=[],
                recommended_action="continue_monitoring", evaluated_at=started,
                data_status="insufficient_or_stale",
            ),
        )
        with self._lock:  # route lookup above may be slow; only lock the insert
            self.journeys[j.id] = j
        return j

    def get(self, journey_id: str) -> Journey:
        j = self.journeys.get(journey_id)
        if not j:
            raise not_found("journey", journey_id)
        return j

    def _get_active(self, journey_id: str) -> Journey:
        j = self.get(journey_id)
        if j.status != "active":
            raise ApiError(409, "journey_not_active", f"Journey is already {j.status}.")
        return j

    @_locked
    def _end(self, journey_id: str, status: str) -> Journey:
        j = self._get_active(journey_id)
        j.status = status  # type: ignore[assignment]
        j.ended_at = j.reference_time()
        for c in self.checkins.values():
            if c.journey_id == j.id and c.status == "open":
                c.status = "closed"
        self._resolve_no_signal(j)
        self.events.publish("journey_ended", j.id, {
            "journey_id": j.id, "status": j.status, "ended_at": j.ended_at})
        return j

    def complete(self, journey_id: str) -> Journey:
        return self._end(journey_id, "completed")

    def cancel(self, journey_id: str) -> Journey:
        return self._end(journey_id, "cancelled")

    # ---------------------------------------------------------- GPS + escalation
    @_locked
    def add_location(self, journey_id: str, req: LocationUpdate) -> LocationResult:
        j = self._get_active(journey_id)
        ts = req.timestamp or _now()
        if j.track and ts < j.track[-1].timestamp:
            raise ApiError(
                422, "out_of_order_timestamp",
                "timestamp is earlier than the previous GPS update.",
                {"previous": j.track[-1].timestamp.isoformat()},
            )
        point = TrackPoint(latitude=req.latitude, longitude=req.longitude, timestamp=ts,
                           accuracy_m=req.accuracy_m)
        j.track.append(point)
        j.last_seen_at = _now()
        self._resolve_no_signal(j)  # the phone is talking again

        risk = assess(j, self.risk_config)  # recalculated from scratch, never accumulated
        j.risk = risk
        checkin = alert = None
        dedup = False

        if risk.level != "high":
            j.high_alert_latched = False

        if risk.level == "high":
            if j.high_alert_latched or self._open_alert(j.id, "risk"):
                dedup = True
            else:
                alert = self._make_alert(j, risk, "risk", "high")
            j.high_alert_latched = True
        elif risk.level == "medium":
            if self._checkin_allowed(j):
                checkin = self._make_checkin(j, risk)
            else:
                dedup = True

        self.events.publish("risk_updated", j.id, {
            "journey_id": j.id, "location": point, "risk": risk})
        return LocationResult(
            journey_id=j.id, journey_status=j.status, location=point, risk=risk,
            checkin_created=checkin, alert_created=alert, deduplicated=dedup,
        )

    # ---------------------------------------------------------- no-signal watchdog
    @_locked
    def check_silence(self, now: datetime | None = None) -> list[Alert]:
        """Raise one no_signal alert for each active journey whose phone has been
        silent longer than `no_signal_after` (wall-clock time, not GPS time).
        Called periodically by the background watchdog; safe to call any time."""
        now = now or _now()
        raised = []
        for j in self.journeys.values():
            if j.status != "active" or not j.signal_watch or j.last_seen_at is None:
                continue
            silent = now - j.last_seen_at
            if silent <= self.no_signal_after or self._open_alert(j.id, "no_signal"):
                continue
            last = j.latest_location
            where = (f" Last known position {last.latitude:.5f}, {last.longitude:.5f}."
                     if last else " No position was ever received.")
            raised.append(self._make_alert(
                j, j.risk, "no_signal", "high",
                message=(f"No location from {j.user_name} for {_duration(silent)} "
                         f"on the way to {j.destination.name}.{where} "
                         f"Their phone may be off, out of battery or without signal."),
                created_at=now,
            ))
        return raised

    def _resolve_no_signal(self, j: Journey) -> None:
        a = self._open_alert(j.id, "no_signal")
        if a:
            a.resolved_at = _now()
            self.events.publish("alert_resolved", j.id, a)

    def _open_alert(self, journey_id: str, kind: str) -> Alert | None:
        for a in self.alerts.values():
            if (a.journey_id == journey_id and a.type == kind
                    and not a.acknowledged and a.resolved_at is None):
                return a
        return None

    def _open_checkin(self, journey_id: str) -> CheckIn | None:
        for c in reversed(list(self.checkins.values())):
            if c.journey_id == journey_id and c.status == "open":
                return c
        return None

    def _checkin_allowed(self, j: Journey) -> bool:
        if self._open_checkin(j.id):
            return False
        ref = j.reference_time()
        return j.last_checkin_at is None or ref - j.last_checkin_at >= CHECKIN_COOLDOWN

    def _make_checkin(self, j: Journey, risk: RiskAssessment) -> CheckIn:
        c = CheckIn(
            journey_id=j.id,
            created_at=j.reference_time(),
            message=_checkin_message(j, risk),
            options=CHECKIN_OPTIONS,
            risk_score=risk.score,
            reason_codes=[r.code for r in risk.reasons],
        )
        self.checkins[c.id] = c
        j.last_checkin_at = c.created_at
        self.events.publish("checkin_created", j.id, c)
        return c

    def _make_alert(self, j: Journey, risk: RiskAssessment, kind: str, priority: str,
                    message: str | None = None, created_at: datetime | None = None) -> Alert:
        if message:
            msg = message
        elif kind == "help_request":
            msg = f"URGENT: {j.user_name} pressed the help button on the way to {j.destination.name}."
        else:
            why = "; ".join(r.description.rstrip(".") for r in risk.reasons) or "elevated risk"
            msg = (f"{j.user_name} may need assistance on the way to {j.destination.name}. "
                   f"Risk {risk.score}/100 ({why})")
        a = Alert(
            journey_id=j.id, user_name=j.user_name, type=kind, priority=priority,  # type: ignore[arg-type]
            message=msg, risk_score=risk.score, risk_level=risk.level,
            reasons=risk.reasons, location=j.latest_location,
            created_at=created_at or j.reference_time(),
        )
        self.alerts[a.id] = a
        self.events.publish("alert_created", j.id, a)
        return a

    # ---------------------------------------------------------- check-in endpoint
    @_locked
    def checkin(self, journey_id: str, req: CheckInRequest) -> CheckInResult:
        j = self._get_active(journey_id)
        if req.help_requested:
            j.help_requested = True
            j.risk = assess(j, self.risk_config)
            existing = self._open_alert(j.id, "help_request")
            if existing:
                return CheckInResult(journey_id=j.id, risk=j.risk, alert=existing, deduplicated=True)
            alert = self._make_alert(j, j.risk, "help_request", "critical")
            return CheckInResult(journey_id=j.id, risk=j.risk, alert=alert)

        if req.checkin_id:
            c = self.checkins.get(req.checkin_id)
            if not c or c.journey_id != j.id:
                raise not_found("checkin", req.checkin_id)
        else:
            c = self._open_checkin(j.id)
            if not c:
                raise ApiError(404, "no_open_checkin", "There is no open check-in to answer.")
        c.status = "answered"
        c.response = req.response
        c.answered_at = j.reference_time()
        self.events.publish("checkin_answered", j.id, c)
        return CheckInResult(journey_id=j.id, risk=j.risk, checkin=c)

    def journey_checkins(self, journey_id: str) -> list[CheckIn]:
        self.get(journey_id)
        return [c for c in self.checkins.values() if c.journey_id == journey_id]

    # ---------------------------------------------------------- alerts
    def list_alerts(self, journey_id: str | None = None, acknowledged: bool | None = None) -> list[Alert]:
        out = list(self.alerts.values())
        if journey_id:
            out = [a for a in out if a.journey_id == journey_id]
        if acknowledged is not None:
            out = [a for a in out if a.acknowledged == acknowledged]
        return list(reversed(out))  # newest first

    @_locked
    def acknowledge(self, alert_id: str) -> Alert:
        a = self.alerts.get(alert_id)
        if not a:
            raise not_found("alert", alert_id)
        if not a.acknowledged:
            a.acknowledged = True
            a.acknowledged_at = _now()
            self.events.publish("alert_acknowledged", a.journey_id, a)
        return a
