"""The explainable risk engine.

The score is RECOMPUTED from the journey's current conditions every time
(it is never added up across GPS updates). Each rule is independent, adds a
fixed number of points, and explains itself in plain language.

These are experimental navigation heuristics, NOT medical indicators.
"""
from __future__ import annotations

from datetime import timedelta

from .geo import distance_to_route_m, haversine_m
from .models import Journey, RiskAssessment, RiskReason, TrackPoint

# ---- points per rule
POINTS_SAFE_ZONE = 15
POINTS_OFF_ROUTE = 25
POINTS_STATIONARY = 15
POINTS_REVISITS = 25
POINTS_LATE = 20

# ---- thresholds
OFF_ROUTE_M = 100.0
STATIONARY_MIN_SECONDS = 5 * 60       # "more than five minutes"
STATIONARY_RADIUS_M = 25.0            # GPS jitter tolerance
ARRIVAL_RADIUS_M = 50.0               # within this of destination = arrived
LATE_GRACE = timedelta(minutes=10)
REVISIT_RADIUS_M = 30.0               # points this close count as the same place
REVISIT_THRESHOLD = 3                 # revisits needed to be "repeated"

MEDIUM_MIN = 30
HIGH_MIN = 60


def level_for(score: int) -> str:
    if score >= HIGH_MIN:
        return "high"
    if score >= MEDIUM_MIN:
        return "medium"
    return "low"


# ------------------------------------------------------------------ rules
def has_arrived(j: Journey) -> bool:
    d = j.destination
    return any(
        haversine_m(p.latitude, p.longitude, d.latitude, d.longitude) <= ARRIVAL_RADIUS_M
        for p in j.track
    )


def _inside(z, lat: float, lon: float) -> bool:
    return haversine_m(z.latitude, z.longitude, lat, lon) <= z.radius_m


def check_safe_zone(j: Journey) -> RiskReason | None:
    """Safe zones are small circles around places (e.g. Home, the destination).
    Leaving the zone you START in is expected, so zones containing the start never
    score. A remaining zone scores only if she ARRIVED inside it earlier in the
    journey and the latest position is now outside every such zone."""
    applicable = [
        z for z in j.safe_zones
        if not _inside(z, j.start.latitude, j.start.longitude)
    ]
    if not applicable or len(j.track) < 2:
        return None
    last = j.track[-1]
    if any(_inside(z, last.latitude, last.longitude) for z in applicable):
        return None
    was_inside = any(
        _inside(z, p.latitude, p.longitude) for z in applicable for p in j.track[:-1]
    )
    if not was_inside:
        return None
    names = ", ".join(z.name for z in applicable)
    return RiskReason(
        code="left_safe_zone",
        points=POINTS_SAFE_ZONE,
        description=f"Arrived at a safe zone ({names}) and then moved outside it.",
    )


def check_off_route(j: Journey) -> RiskReason | None:
    if not j.track:
        return None
    last = j.track[-1]
    dist = distance_to_route_m(last.latitude, last.longitude, j.route)
    if dist > OFF_ROUTE_M:
        return RiskReason(
            code="off_route",
            points=POINTS_OFF_ROUTE,
            description=f"{dist:.0f} m away from the expected route (limit {OFF_ROUTE_M:.0f} m).",
        )
    return None


def check_stationary(j: Journey) -> RiskReason | None:
    if len(j.track) < 2:
        return None
    last = j.track[-1]
    d = j.destination
    if haversine_m(last.latitude, last.longitude, d.latitude, d.longitude) <= ARRIVAL_RADIUS_M:
        return None  # standing at the destination is fine
    first = last
    for p in reversed(j.track[:-1]):
        if haversine_m(p.latitude, p.longitude, last.latitude, last.longitude) > STATIONARY_RADIUS_M:
            break
        first = p
    seconds = (last.timestamp - first.timestamp).total_seconds()
    if seconds > STATIONARY_MIN_SECONDS:
        return RiskReason(
            code="stationary",
            points=POINTS_STATIONARY,
            description=f"Hasn't moved more than {STATIONARY_RADIUS_M:.0f} m for {seconds / 60:.1f} minutes.",
        )
    return None


def count_revisits(track: list[TrackPoint]) -> int:
    """Count how many times the user came back to a place they had already been.

    Idea: remember 'anchor' places (a new anchor is created whenever a GPS point is
    more than 30 m from every existing anchor). Each time the walker's current anchor
    changes to one visited before, that is one revisit. Staying put never counts.
    Simply retracing your steps (stepping back to the anchor you were at just before
    the current one, e.g. a single turn-around) is treated as backtracking, not a loop;
    circling a block or pacing back and forth repeatedly still counts."""
    anchors: list[TrackPoint] = []
    path: list[int] = []  # anchors in the order walked (backtracking pops)
    current: int | None = None
    revisits = 0
    for p in track:
        best, best_d = None, REVISIT_RADIUS_M
        for i, a in enumerate(anchors):
            d = haversine_m(p.latitude, p.longitude, a.latitude, a.longitude)
            if d <= best_d:
                best, best_d = i, d
        if best is None:
            anchors.append(p)
            current = len(anchors) - 1
            path.append(current)
            continue
        if best != current:
            if len(path) >= 2 and path[-2] == best:
                path.pop()  # stepped back along the way we came
            else:
                revisits += 1
                path.append(best)
            current = best
    return revisits


def check_revisits(j: Journey) -> RiskReason | None:
    n = count_revisits(j.track)
    if n >= REVISIT_THRESHOLD:
        return RiskReason(
            code="repeated_revisits",
            points=POINTS_REVISITS,
            description=f"Has returned to previously visited locations {n} times.",
        )
    return None


def check_late(j: Journey) -> RiskReason | None:
    if has_arrived(j):
        return None
    late_by = j.reference_time() - j.expected_arrival
    if late_by > LATE_GRACE:
        return RiskReason(
            code="late_arrival",
            points=POINTS_LATE,
            description=f"{late_by.total_seconds() / 60:.0f} minutes past expected arrival and not at destination.",
        )
    return None


# ------------------------------------------------------------------ main
def assess(j: Journey) -> RiskAssessment:
    reasons = [
        r
        for r in (
            check_safe_zone(j),
            check_off_route(j),
            check_stationary(j),
            check_revisits(j),
            check_late(j),
        )
        if r is not None
    ]
    score = min(100, sum(r.points for r in reasons))
    level = level_for(score)
    if j.help_requested:
        action = "immediate_caregiver_alert"
    else:
        action = {
            "low": "continue_monitoring",
            "medium": "contextual_check_in",
            "high": "caregiver_alert",
        }[level]
    return RiskAssessment(
        score=score,
        level=level,  # type: ignore[arg-type]
        reasons=reasons,
        recommended_action=action,  # type: ignore[arg-type]
        help_requested=j.help_requested,
        evaluated_at=j.reference_time(),
    )
