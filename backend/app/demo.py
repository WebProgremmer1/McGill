"""Scripted demo: a fictional user walks to Tim Hortons, gets lost, and escalates.

It feeds simulated GPS points (with simulated timestamps) through the REAL
JourneyService / risk engine. Nothing here is a hardcoded score.

Run from the backend folder:  python -m app.demo
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import Settings
from .geo import interpolate_route, offset_point
from .models import JourneyCreate, LocationUpdate, Place, SafeZone
from .routes_provider import PREDEFINED_ROUTES, RouteProvider
from .service import JourneyService

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def _timeline(route):
    """Yield (minute, phase, description, lat, lng)."""
    # unit vectors (north, east) along the walk, and perpendicular to it
    heading = (0.6, 0.8)
    perp = (0.8, -0.6)

    def at(base, n_along, n_perp):
        return offset_point(
            base[0], base[1],
            heading[0] * n_along + perp[0] * n_perp,
            heading[1] * n_along + perp[1] * n_perp,
        )

    # 1. normal walking
    for m in (0, 2, 4):
        lat, lng = interpolate_route(route, m / 10)
        yield m, "normal", "Walking normally along the route", lat, lng

    # 2. leaves the route
    branch = interpolate_route(route, 0.4)
    yield 5, "deviation", "Turns down a side street", *at(branch, 0, 250)

    # 3. walks round the same three corners twice
    base = at(branch, 0, 300)
    corners = {"A": at(base, 0, 0), "B": at(base, 70, 0), "C": at(base, 70, 70)}
    for i, c in enumerate("ABCABC"):
        yield 6 + i, "loop", f"Circling the block (corner {c})", *corners[c]

    # 4. stands still for 7 minutes
    clat, clng = corners["C"]
    yield 12, "stationary", "Stops and stands still", clat, clng
    yield 18, "stationary", "Still standing, looks confused", clat, clng


def run_demo(service: JourneyService | None = None) -> dict:
    service = service or JourneyService(RouteProvider(Settings(route_mode="offline")))
    route_pts = PREDEFINED_ROUTES["tim_hortons_demo"]
    start, end = route_pts[0], route_pts[-1]

    journey = service.create_journey(JourneyCreate(
        user_name="Margaret",
        start=Place(name="Home", latitude=start[0], longitude=start[1]),
        destination=Place(name="Tim Hortons", latitude=end[0], longitude=end[1]),
        expected_arrival=T0 + timedelta(minutes=15),
        started_at=T0,
        predefined_route="tim_hortons_demo",
        safe_zones=[
            SafeZone(name="Home", latitude=start[0], longitude=start[1], radius_m=75),
            SafeZone(name="Tim Hortons", latitude=end[0], longitude=end[1], radius_m=75),
        ],
    ))

    steps = []
    first = {"medium": None, "high": None}
    for minute, phase, desc, lat, lng in _timeline(journey.route):
        res = service.add_location(journey.id, LocationUpdate(
            latitude=lat, longitude=lng, timestamp=T0 + timedelta(minutes=minute)))
        for lvl in ("medium", "high"):
            if res.risk.level == lvl and first[lvl] is None:
                first[lvl] = minute
        steps.append({
            "minute": minute,
            "phase": phase,
            "description": desc,
            "latitude": lat,
            "longitude": lng,
            "score": res.risk.score,
            "level": res.risk.level,
            "reasons": [r.code for r in res.risk.reasons],
            "checkin_created": res.checkin_created.message if res.checkin_created else None,
            "alert_created": res.alert_created.message if res.alert_created else None,
        })

    return {
        "journey_id": journey.id,
        "summary": {
            "first_medium_at_minute": first["medium"],
            "first_high_at_minute": first["high"],
            "final_score": steps[-1]["score"],
            "checkins_created": len(service.journey_checkins(journey.id)),
            "alerts_created": len(service.list_alerts(journey.id)),
            "note": "Simulated data; scores come from the real risk engine.",
        },
        "steps": steps,
    }


if __name__ == "__main__":
    out = run_demo()
    print(f"{'min':>3} {'score':>5} {'level':<7} {'phase':<20} reasons")
    for s in out["steps"]:
        print(f"{s['minute']:>3} {s['score']:>5} {s['level']:<7} {s['phase']:<20} {','.join(s['reasons'])}")
        if s["checkin_created"]:
            print(f"      >> CHECK-IN: {s['checkin_created']}")
        if s["alert_created"]:
            print(f"      >> CAREGIVER ALERT: {s['alert_created']}")
    print("\nSummary:", out["summary"])
