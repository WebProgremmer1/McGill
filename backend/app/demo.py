"""Scripted demo: a fictional user walks to Tim Hortons, gets lost, and escalates.

It feeds pretend GPS points (with pretend timestamps) through the REAL
JourneyService and risk engine. No score here is hardcoded.

Run from the backend folder:  python -m app.demo
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import Settings
from .geo import offset_point
from .models import JourneyCreate, LocationUpdate, Place, SafeZone
from .routes_provider import PREDEFINED_ROUTES, RouteProvider
from .service import JourneyService

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


def _timeline(route):
    """Yield (minute, phase, description, lat, lng)."""
    # 1. normal walking along the first three route points
    for minute, p in zip((0, 2, 4), route):
        yield minute, "normal", "Walking normally along the route", p.latitude, p.longitude

    # 2. turns off to the south-east (the route goes north-east)
    turn = route[2]
    yield 5, "deviation", "Turns down a side street", *offset_point(turn.latitude, turn.longitude, -80, 80)

    # 3. walks round the same block twice (corners A -> B -> C)
    a = offset_point(turn.latitude, turn.longitude, -180, 180)
    b = offset_point(*a, -70, 0)   # 70 m south of A
    c = offset_point(*a, -70, 70)  # then 70 m east
    corners = {"A": a, "B": b, "C": c}
    for i, name in enumerate("ABCABC"):
        yield 6 + i, "loop", f"Circling the block (corner {name})", *corners[name]

    # 4. stops at corner C and stands still
    yield 12, "stationary", "Stops and stands still", *c
    yield 18, "stationary", "Still standing, looks confused", *c


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
            "reason_details": [f"{r.description} (+{r.points})" for r in res.risk.reasons],
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
    print(f"{'min':>3} {'score':>5} {'level':<7} {'phase':<11} reasons")
    for s in out["steps"]:
        print(f"{s['minute']:>3} {s['score']:>5} {s['level']:<7} {s['phase']:<11} {'; '.join(s['reason_details'])}")
        if s["checkin_created"]:
            print(f"      >> CHECK-IN: {s['checkin_created']}")
        if s["alert_created"]:
            print(f"      >> CAREGIVER ALERT: {s['alert_created']}")
    print("\nSummary:", out["summary"])
