"""Direction-aware off-route scoring (#6) and recognising 'back on track' (#5)."""
import math

from conftest import HOME, SHOP, far_off_route, iso, make_journey
from app.geo import haversine_m, offset_point

M_PER_DEG = 111_320.0


def codes(res):
    return [r["code"] for r in res["risk"]["reasons"]]


def points(res, code):
    return next(r["points"] for r in res["risk"]["reasons"] if r["code"] == code)


def send(client, jid, p, minute):
    r = client.post(f"/api/journeys/{jid}/location",
                    json={"latitude": p[0], "longitude": p[1], "timestamp": iso(minute), "accuracy_m": 5})
    assert r.status_code == 200, r.text
    return r.json()


def step(p, target, metres, turn_deg=0.0):
    """Move `metres` from p towards target, optionally turned by `turn_deg` (180 = directly away)."""
    north = (target[0] - p[0]) * M_PER_DEG
    east = (target[1] - p[1]) * M_PER_DEG * math.cos(math.radians(p[0]))
    angle = math.atan2(north, east) + math.radians(turn_deg)
    return offset_point(p[0], p[1], metres * math.sin(angle), metres * math.cos(angle))


# A spot ~200 m north-west of the planned Home -> Tim Hortons route.
OFF = offset_point(HOME[0], HOME[1], 199, -151)


def walk(client, jid, turn_deg, minutes=2.0, start=OFF, speed_m_per_min=78):
    """Walk from `start`, one GPS update every 30 s, in a direction relative to Tim Hortons."""
    p, res = start, None
    for i in range(int(minutes * 2) + 1):
        res = send(client, jid, p, i / 2)
        p = step(p, SHOP, speed_m_per_min / 2, turn_deg)
    return res


# ---------------------------------------------------------------- #6 direction of travel
def test_other_street_towards_destination_is_low_risk(client):
    j = make_journey(client)
    res = walk(client, j["id"], turn_deg=0)
    assert codes(res) == ["off_route"]
    assert res["risk"]["heading"] == "toward"
    assert res["risk"]["level"] == "low"
    assert points(res, "off_route") == 5                      # small detour
    assert res["risk"]["detour_extra_min"] < 5
    assert "heading towards Tim Hortons" in res["risk"]["reasons"][0]["description"]


def test_detour_points_grow_with_the_extra_minutes(client):
    by_delay = {}
    for started in (0, -8, -30):                               # same walk, trip begun earlier
        j = make_journey(client, started_at=iso(started))
        res = walk(client, j["id"], turn_deg=0)
        by_delay[res["risk"]["detour_extra_min"]] = points(res, "off_route")
    delays = sorted(by_delay)
    assert [by_delay[d] for d in delays] == [5, 15, 20]        # +5 per 5 extra min, capped at 20
    assert delays[1] >= 10 and delays[2] >= 15


def test_away_and_stopped_score_more_than_sideways_and_towards(client):
    scores = {}
    for name, turn in (("toward", 0), ("sideways", 90), ("away", 180)):
        res = walk(client, make_journey(client)["id"], turn_deg=turn)
        assert res["risk"]["heading"] == name, name
        scores[name] = points(res, "off_route")
    j = make_journey(client)
    for m in (0, 0.5, 1, 1.5, 2):
        res = send(client, j["id"], OFF, m)
    assert res["risk"]["heading"] == "stopped"
    scores["stopped"] = points(res, "off_route")
    assert scores == {"toward": 5, "sideways": 25, "away": 30, "stopped": 30}


def test_away_checkin_says_so(client):
    j = make_journey(client)
    res = walk(client, j["id"], turn_deg=180)
    assert res["risk"]["level"] == "medium"
    checkins = client.get(f"/api/journeys/{j['id']}/checkins").json()
    assert len(checkins) == 1 and "heading away from Tim Hortons" in checkins[0]["message"]


def test_direction_needs_some_history(client):
    j = make_journey(client)
    res = send(client, j["id"], OFF, 0)
    assert res["risk"]["heading"] is None and res["risk"]["making_progress"] is None


# ---------------------------------------------------------------- #5 back on track
def square(minute0=0):
    a = far_off_route(0, -300)
    b = offset_point(*a, 0, 70)
    c = offset_point(*b, 70, 0)
    d = offset_point(*a, 70, 0)
    return [a, b, c, d, a, b, c, d, a, b, c]                  # round the block twice and a bit


def test_circles_twice_then_finds_the_way(client):
    j = make_journey(client)
    loop = square()
    for i, p in enumerate(loop):
        res = send(client, j["id"], p, i)
    assert "repeated_revisits" in codes(res)
    assert res["risk"]["making_progress"] is False            # a loop is not progress
    p, minute = loop[-1], len(loop) - 1
    for _ in range(6):                                         # finds the right street
        minute += 1
        p = step(p, SHOP, 75)
        res = send(client, j["id"], p, minute)
    risk = res["risk"]
    assert risk["making_progress"] is True and risk["heading"] == "toward"
    assert risk["progress_m"] > 300
    assert "repeated_revisits" not in codes(res)
    assert risk["level"] == "low"


def test_old_loops_expire_even_without_progress(client):
    j = make_journey(client)
    loop = square()
    for i, p in enumerate(loop):
        send(client, j["id"], p, i)
    p = loop[-1]
    res = None
    for minute in range(len(loop), 30):                        # walks off west, no progress
        p = offset_point(*p, 0, -60)
        res = send(client, j["id"], p, minute)
        if minute == 16:
            assert "repeated_revisits" in codes(res)           # loop still recent
    assert "repeated_revisits" not in codes(res)               # >15 min ago: history
    assert res["risk"]["heading"] == "away"


def test_progress_is_reported_in_stateless_analysis(client):
    route = [list(HOME), list(SHOP)]
    history, p = [], HOME
    for i in range(12):                                        # straight to the shop
        history.append({"latitude": p[0], "longitude": p[1], "timestamp": iso(i / 2), "accuracy_meters": 5})
        p = step(p, SHOP, 39)
    out = client.post("/api/analyze-journey", json={"gps_history": history, "expected_route": route}).json()
    assert out["risk"]["making_progress"] is True and out["risk"]["heading"] == "toward"
    assert out["risk"]["score"] == 0
