"""The risk score (0-100). Five rules: off route, standing still, going in loops,
left a safe zone, taking too long.

Every time a new GPS point arrives the score is worked out again from the
whole track. Points are never carried over from the last update, so if she
gets back on route the off-route points disappear.

Experimental navigation heuristics, NOT a medical measure.
"""
from __future__ import annotations

from .geo import distance_m, distance_to_route_m
from .models import Journey, RiskAssessment, RiskReason

ON_ROUTE_M = 50          # up to 50 m from the route still counts as on route
ARRIVED_M = 50           # this close to the destination = arrived


def minutes_between(a, b) -> float:
    return (b.timestamp - a.timestamp).total_seconds() / 60


# ---------------------------------------------------------------- rule 1
def off_route(j: Journey) -> RiskReason | None:
    """Points for HOW FAR off route she is + points for HOW LONG she has been off."""
    last = j.track[-1]
    metres = distance_to_route_m(last, j.route)
    if metres <= ON_ROUTE_M:
        return None

    # How far: three bands, so 60 m off and 1 km off are not treated the same.
    if metres > 300:
        far_points, how_far = 40, "Far off route"
    elif metres > 150:
        far_points, how_far = 25, "Off route"
    else:
        far_points, how_far = 10, "A little off route"

    # How long: go back through the track to the first point of this off-route stretch.
    since = last
    for p in reversed(j.track):
        if distance_to_route_m(p, j.route) <= ON_ROUTE_M:
            break
        since = p
    minutes = minutes_between(since, last)
    time_points = min(40, int(minutes * 2))  # 2 points per minute, max 40

    return RiskReason(code="off_route", points=far_points + time_points,
                      description=f"{how_far} ({metres:.0f} m away) for {minutes:.0f} min.")


# ---------------------------------------------------------------- rule 2
def standing_still(j: Journey) -> RiskReason | None:
    """Points for every minute she stays in the same spot (after 2 free minutes)."""
    last = j.track[-1]
    if distance_m(last, j.destination) <= ARRIVED_M:
        return None  # waiting at the destination is fine

    # Go back through the track while she was within 25 m of where she is now.
    since = last
    for p in reversed(j.track):
        if distance_m(p, last) > 25:
            break
        since = p
    minutes = minutes_between(since, last)
    points = min(25, int((minutes - 2) * 3))  # 3 points per minute after 2 min, max 25
    if points <= 0:
        return None
    return RiskReason(code="stationary", points=points,
                      description=f"Standing still for {minutes:.0f} min.")


# ---------------------------------------------------------------- rule 3
def going_in_loops(j: Journey) -> RiskReason | None:
    """Points for every time she comes BACK to the spot she is at now."""
    last = j.track[-1]
    # Walk through the track and count how many separate times she was
    # within 30 m of her current spot (arrive, leave, arrive again = 2 visits).
    visits, was_here = 0, False
    for p in j.track:
        here = distance_m(p, last) <= 30
        if here and not was_here:
            visits += 1
        was_here = here
    returns = visits - 1  # the first visit is not a return
    points = min(30, returns * 15)  # 15 points per return, max 30
    if points <= 0:
        return None
    return RiskReason(code="repeated_revisits", points=points,
                      description=f"Came back to this spot {returns} time(s).")


# ---------------------------------------------------------------- rule 4
def left_safe_zone(j: Journey) -> RiskReason | None:
    """15 points if she got to a safe zone (e.g. Tim Hortons) and then walked out of it."""
    # Zones around the start (Home) are skipped: leaving home is expected.
    zones = [z for z in j.safe_zones if distance_m(j.start, z) > z.radius_m]

    def inside_a_zone(p) -> bool:
        return any(distance_m(p, z) <= z.radius_m for z in zones)

    last = j.track[-1]
    was_inside_before = any(inside_a_zone(p) for p in j.track)
    if was_inside_before and not inside_a_zone(last):
        return RiskReason(code="left_safe_zone", points=15,
                          description="Reached a safe zone, then left it.")
    return None


# ---------------------------------------------------------------- rule 5
def taking_too_long(j: Journey) -> RiskReason | None:
    """Points when the whole trip is taking much longer than it should."""
    if any(distance_m(p, j.destination) <= ARRIVED_M for p in j.track):
        return None  # she got there, so the trip is over

    expected_min = max(0, (j.expected_arrival - j.started_at).total_seconds() / 60)
    allowed_min = expected_min * 1.5  # 50% extra: older people walk slower than maps assume
    walking_min = (j.track[-1].timestamp - j.started_at).total_seconds() / 60
    points = min(30, int((walking_min - allowed_min) * 2))  # 2 points per minute over, max 30
    if points <= 0:
        return None
    return RiskReason(code="taking_too_long", points=points,
                      description=f"Walking for {walking_min:.0f} min; this walk should take about {expected_min:.0f} min.")


# ---------------------------------------------------------------- total
def level_for(score: int) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


ACTIONS = {"low": "continue_monitoring", "medium": "contextual_check_in", "high": "caregiver_alert"}


# ---------------------------------------------------------------- her answers
def ignored_checkin(j: Journey) -> RiskReason | None:
    """+15 if the phone asked "Are you okay?", she hasn't answered for 2+ minutes,
    and she kept walking (if she stopped, the standing-still rule covers it)."""
    if j.checkin_sent_at is None:
        return None
    minutes = (j.reference_time() - j.checkin_sent_at).total_seconds() / 60
    if minutes < 2:
        return None
    if distance_m(j.track[-1], j.checkin_sent_where) <= 25:
        return None  # hasn't moved since the question
    return RiskReason(code="ignored_checkin", points=15,
                      description=f"Hasn't answered the check-in for {minutes:.0f} min and kept walking.")


def said_okay(j: Journey, score: int) -> RiskReason | None:
    """-15 points for the rest of the walk once she answers "I'm okay".
    Answering again never takes off more than 15."""
    if j.okay_at is None or score <= 0:
        return None
    minute = (j.okay_at - j.started_at).total_seconds() / 60
    return RiskReason(code="said_okay", points=-15,
                      description=f"Said she was okay at minute {minute:.0f}.")


def assess(j: Journey) -> RiskAssessment:
    reasons = []
    if j.track:
        for rule in (off_route, standing_still, going_in_loops, left_safe_zone, taking_too_long, ignored_checkin):
            reason = rule(j)
            if reason:
                reasons.append(reason)
    okay = said_okay(j, sum(r.points for r in reasons))
    if okay:
        reasons.append(okay)
    score = max(0, min(100, sum(r.points for r in reasons)))
    level = level_for(score)
    action = "immediate_caregiver_alert" if j.help_requested else ACTIONS[level]
    return RiskAssessment(score=score, level=level, reasons=reasons,
                          recommended_action=action, help_requested=j.help_requested,
                          evaluated_at=j.reference_time())
