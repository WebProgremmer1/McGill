import httpx

from app.config import Settings
from app.demo import run_demo
from app.geo import decode_polyline, offset_point
from app.main import create_app
from app.models import Coordinates
from app.routes_provider import RouteProvider
from fastapi.testclient import TestClient

from conftest import HOME, SHOP, far_off_route, iso, make_journey, send


def codes(result):
    return [r["code"] for r in result["risk"]["reasons"]]


# ---------------------------------------------------------------- journeys
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_create_journey(client):
    j = make_journey(client)
    assert j["id"].startswith("jrn_")
    assert j["status"] == "active"
    assert j["route_source"] == "predefined"
    assert len(j["route"]) == 5
    assert j["risk"]["score"] == 0 and j["risk"]["level"] == "low"
    assert client.get(f"/api/journeys/{j['id']}").json()["id"] == j["id"]


def test_create_journey_without_key_uses_fallback_with_warning(client):
    j = make_journey(client, predefined_route=None)
    assert j["route_source"] == "fallback_straight_line"
    assert "straight-line" in j["route_warning"]


def test_unknown_journey_404(client):
    r = client.get("/api/journeys/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "journey_not_found"


def test_unknown_predefined_route(client):
    r = client.post("/api/journeys", json={
        "start": {"name": "A", "latitude": 1, "longitude": 1},
        "destination": {"name": "B", "latitude": 1, "longitude": 1.001},
        "expected_arrival": iso(10), "predefined_route": "nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_predefined_route"


# ---------------------------------------------------------------- rules
def test_normal_walk_is_low_risk(client, journey):
    res = send(client, journey["id"], *HOME, 0)
    res = send(client, journey["id"], journey["route"][1]["latitude"], journey["route"][1]["longitude"], 2)
    assert res["risk"]["score"] == 0
    assert res["risk"]["recommended_action"] == "continue_monitoring"


def points(res, code):
    return next((r["points"] for r in res["risk"]["reasons"] if r["code"] == code), 0)


def test_distance_in_metres():
    from app.geo import distance_m, distance_to_route_m
    from app.models import Coordinates as C
    home = C(latitude=HOME[0], longitude=HOME[1])
    north = C(latitude=HOME[0] + 0.001, longitude=HOME[1])
    assert round(distance_m(home, north)) == 111          # 0.001 degrees of latitude = 111 m
    east = C(latitude=HOME[0], longitude=HOME[1] + 0.001)
    assert round(distance_m(home, east)) == 78            # shorter: multiplied by cos(45.5 deg)
    route = [C(latitude=45.0, longitude=-73.0), C(latitude=45.0, longitude=-72.99)]   # east-west line
    beside = C(latitude=45.0 + 100 / 111_320, longitude=-72.995)                     # 100 m north of its middle
    assert round(distance_to_route_m(beside, route)) == 100


def test_off_route_bands(client):
    # one GPS point each, so no time has passed yet: only the distance band counts
    # (the route heads north-east from Home, so points west of Home are this far off it)
    def first_point(west_m):
        j = make_journey(client)
        return points(send(client, j["id"], *far_off_route(0, -west_m), 0), "off_route")
    assert first_point(30) == 0       # within 50 m = on route
    assert first_point(100) == 10     # a little off route
    assert first_point(200) == 25     # off route
    assert first_point(1000) == 40    # far off route


def test_off_route_grows_with_time(client, journey):
    spot = far_off_route(0, -400)        # far off route: 40 points
    got = {m: points(send(client, journey["id"], *offset_point(*spot, 0, -40 * m), m), "off_route")
           for m in range(0, 25)}        # keeps walking west, so never "standing still"
    assert got[0] == 40
    assert got[5] == 50                  # +2 points per minute off route
    assert got[24] == 80                 # time part capped at 40
    back = send(client, journey["id"], *HOME, 25)
    assert points(back, "off_route") == 0   # back on route: recalculated, not added up


def test_a_little_off_for_a_long_time_still_escalates(client, journey):
    spot = far_off_route(0, -100)        # 100 m off: only 10 distance points
    res = send(client, journey["id"], *spot, 0)
    assert res["risk"]["level"] == "low"
    for m in range(1, 11):               # pacing up and down the same street for 10 min
        res = send(client, journey["id"], *offset_point(*spot, 40 * (m % 2), 0), m)
    assert points(res, "off_route") == 30   # 10 + 10 min x 2
    assert res["risk"]["level"] in ("medium", "high")


def test_roaming_far_for_a_long_time_alerts_caregiver(client, journey):
    # like the screenshot: zigzag around far from the route, never stopping or looping
    for m in range(0, 16):
        res = send(client, journey["id"], *offset_point(*HOME, -900 + 60 * (m % 2), 900 + 80 * m), m)
    assert res["risk"]["level"] == "high"
    assert len(client.get("/api/alerts").json()) == 1


SHOP_ZONE = {"name": "Tim Hortons", "latitude": SHOP[0], "longitude": SHOP[1], "radius_m": 75}
HOME_ZONE = {"name": "Home", "latitude": HOME[0], "longitude": HOME[1], "radius_m": 75}


def test_safe_zone_exit_after_arriving(client):
    j = make_journey(client, safe_zones=[HOME_ZONE, SHOP_ZONE])
    res = send(client, j["id"], *SHOP, 1)          # arrives inside the zone
    assert "left_safe_zone" not in codes(res)
    lat, lng = offset_point(SHOP[0], SHOP[1], 0, 300)
    res = send(client, j["id"], lat, lng, 2)       # wanders out
    assert points(res, "left_safe_zone") == 15
    res = send(client, j["id"], *SHOP, 3)          # back inside: recalculated
    assert "left_safe_zone" not in codes(res)


def test_leaving_home_zone_never_scores(client):
    j = make_journey(client, safe_zones=[HOME_ZONE, SHOP_ZONE])
    send(client, j["id"], *HOME, 0)
    res = send(client, j["id"], *offset_point(HOME[0], HOME[1], 0, 400), 1)
    assert "left_safe_zone" not in codes(res)


def test_destination_zone_not_scored_before_arriving(client):
    j = make_journey(client, safe_zones=[SHOP_ZONE])
    send(client, j["id"], *HOME, 0)
    res = send(client, j["id"], *far_off_route(), 1)
    assert "left_safe_zone" not in codes(res)


def test_standing_still_grows_with_time(client, journey):
    lat, lng = journey["route"][1]["latitude"], journey["route"][1]["longitude"]
    got = {m: points(send(client, journey["id"], lat, lng, m), "stationary") for m in range(0, 13)}
    assert got[2] == 0                 # first 2 minutes are free
    assert got[5] == 9                 # 3 points per minute after that
    assert got[10] == 24
    assert got[12] == 25               # capped


def test_stationary_at_destination_is_fine(client, journey):
    for m in range(0, 9):
        res = send(client, journey["id"], *SHOP, m)
    assert "stationary" not in codes(res)


def along_route(journey, fraction):
    """A point `fraction` (0..1) of the way along the route (its segments are about equal)."""
    r = journey["route"]
    pos = fraction * (len(r) - 1)
    i = min(int(pos), len(r) - 2)
    t = pos - i
    return (r[i]["latitude"] + (r[i + 1]["latitude"] - r[i]["latitude"]) * t,
            r[i]["longitude"] + (r[i + 1]["longitude"] - r[i]["longitude"]) * t)


def test_taking_too_long(client, journey):
    # expected 15 min -> allowed 22.5 min. She stays on route, creeping ~18 m a minute,
    # so no other rule fires (never off route, never still for 2+ min, never back at a spot).
    got = {m: send(client, journey["id"], *along_route(journey, m / 40), m) for m in range(0, 31)}
    assert points(got[22], "taking_too_long") == 0
    assert points(got[25], "taking_too_long") == 5      # 2.5 min over x 2
    assert points(got[30], "taking_too_long") == 15     # 7.5 min over x 2
    assert codes(got[30]) == ["taking_too_long"]
    arrived = send(client, journey["id"], *SHOP, 31)
    assert "taking_too_long" not in codes(arrived)      # she got there: trip over


def test_taking_too_long_is_capped(client, journey):
    send(client, journey["id"], *HOME, 0)
    res = send(client, journey["id"], *journey_point(journey, 1), 90)   # 90 min into a 15 min walk
    assert points(res, "taking_too_long") == 30


def journey_point(journey, i):
    return journey["route"][i]["latitude"], journey["route"][i]["longitude"]


def test_loops_grow_with_each_return(client, journey):
    a = far_off_route(0, -300)
    square = [a, offset_point(*a, 0, 70), offset_point(*a, 70, 70), offset_point(*a, 70, 0)]
    results = [send(client, journey["id"], *p, i) for i, p in enumerate(square * 2 + [a])]
    assert points(results[3], "repeated_revisits") == 0    # first lap
    assert points(results[4], "repeated_revisits") == 15   # back at a once
    assert points(results[8], "repeated_revisits") == 30   # back at a twice


def test_score_capped_at_100():
    from app.risk import level_for
    assert level_for(29) == "low" and level_for(30) == "medium"
    assert level_for(59) == "medium" and level_for(60) == "high"


# ---------------------------------------------------------------- escalation
def test_medium_creates_checkin_once(client, journey):
    send(client, journey["id"], *HOME, 0)
    # first point far off route: 40 points, no time yet -> medium
    lat, lng = far_off_route(0, -1000)
    res = send(client, journey["id"], lat, lng, 1)
    assert res["risk"]["level"] == "medium"
    assert res["checkin_created"] and "Tim Hortons" in res["checkin_created"]["message"]
    res2 = send(client, journey["id"], lat, lng, 2)
    assert res2["checkin_created"] is None and res2["deduplicated"] is True
    assert len(client.get(f"/api/journeys/{journey['id']}/checkins").json()) == 1


def test_answering_checkin(client):
    j = make_journey(client)
    send(client, j["id"], *HOME, 0)
    send(client, j["id"], *far_off_route(0, -1000), 1)
    r = client.post(f"/api/journeys/{j['id']}/checkin", json={"response": "I'm okay"})
    assert r.status_code == 200 and r.json()["checkin"]["status"] == "answered"
    r = client.post(f"/api/journeys/{j['id']}/checkin", json={"response": "again"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_open_checkin"


def test_explicit_help_request_creates_critical_alert_and_dedupes(client, journey):
    r = client.post(f"/api/journeys/{journey['id']}/checkin", json={"help_requested": True})
    assert r.status_code == 200
    body = r.json()
    assert body["alert"]["priority"] == "critical" and body["alert"]["type"] == "help_request"
    assert body["risk"]["recommended_action"] == "immediate_caregiver_alert"
    again = client.post(f"/api/journeys/{journey['id']}/checkin", json={"help_requested": True}).json()
    assert again["deduplicated"] is True and again["alert"]["id"] == body["alert"]["id"]
    assert len(client.get("/api/alerts").json()) == 1


def test_high_risk_alert_generated_and_deduplicated(client):
    run = client.post("/api/demo/run").json()
    jid = run["journey_id"]
    alerts = client.get("/api/alerts", params={"journey_id": jid}).json()
    assert len(alerts) == 1  # many high-risk updates, one alert
    a = alerts[0]
    assert a["type"] == "risk" and a["priority"] == "high" and a["risk_score"] >= 60


def test_acknowledge_alert_and_no_immediate_realert(client):
    j = make_journey(client)
    # drive to high: far off route (40) + 11 min off route (22) + standing still 11 min (25)
    lat, lng = far_off_route(0, -1000)
    for m in range(0, 12):
        res = send(client, j["id"], lat, lng, m)
    assert res["risk"]["level"] == "high"
    alert = client.get("/api/alerts").json()[0]
    ack = client.post(f"/api/alerts/{alert['id']}/acknowledge").json()
    assert ack["acknowledged"] is True
    res = send(client, j["id"], lat, lng, 12)
    assert res["alert_created"] is None  # still high, but already handled
    assert client.post("/api/alerts/zzz/acknowledge").status_code == 404


# ---------------------------------------------------------------- lifecycle / validation
def test_complete_and_cancel(client, journey):
    r = client.post(f"/api/journeys/{journey['id']}/complete")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    r = client.post(f"/api/journeys/{journey['id']}/location",
                    json={"latitude": 45.5, "longitude": -73.5})
    assert r.status_code == 409 and r.json()["error"]["code"] == "journey_not_active"
    assert client.post(f"/api/journeys/{journey['id']}/complete").status_code == 409
    j2 = make_journey(client)
    assert client.post(f"/api/journeys/{j2['id']}/cancel").json()["status"] == "cancelled"


def test_invalid_gps_coordinates(client, journey):
    for bad in ({"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": -181},
                {"latitude": "abc", "longitude": 0}, {"longitude": 0}):
        r = client.post(f"/api/journeys/{journey['id']}/location", json=bad)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"


def test_out_of_order_timestamp_rejected(client, journey):
    send(client, journey["id"], *HOME, 5)
    r = client.post(f"/api/journeys/{journey['id']}/location",
                    json={"latitude": HOME[0], "longitude": HOME[1], "timestamp": iso(1)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_order_timestamp"


def test_cors_allows_vite(client):
    r = client.options("/api/health", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


# ---------------------------------------------------------------- demo
def test_full_demo_simulation():
    out = run_demo()
    levels = [s["level"] for s in out["steps"]]
    assert levels[0] == "low" and "medium" in levels and levels[-1] == "high"
    assert levels.index("medium") < levels.index("high")
    s = out["summary"]
    assert s["first_medium_at_minute"] == 7 and s["first_high_at_minute"] == 10
    assert s["checkins_created"] == 1 and s["alerts_created"] == 1
    assert out["steps"][-1]["score"] == 96  # off route (40 + 26) + standing still (15) + loop (15)


def test_demo_endpoint_populates_store(client):
    out = client.post("/api/demo/run").json()
    assert client.get(f"/api/journeys/{out['journey_id']}").json()["risk"]["level"] == "high"
    assert len(client.get(f"/api/journeys/{out['journey_id']}/checkins").json()) == 1


# ---------------------------------------------------------------- live map endpoints
def test_maps_config_without_key(client):
    assert client.get("/api/maps-config").json() == {"browser_key": None, "maps_enabled": False}


def test_maps_config_reuses_server_key():
    c = TestClient(create_app(Settings(google_api_key="k", google_browser_key="k")))
    assert c.get("/api/maps-config").json()["maps_enabled"] is True


def test_expected_route_offline_is_straight_line(client):
    r = client.post("/api/expected-route", json={
        "start": {"latitude": HOME[0], "longitude": HOME[1]},
        "destination": {"latitude": SHOP[0], "longitude": SHOP[1]}})
    body = r.json()
    assert r.status_code == 200 and body["route_source"] == "fallback_straight_line"
    assert len(body["route"]) == 2 and 700 < body["distance_m"] < 800


# ---------------------------------------------------------------- Google Routes (mocked)
def _provider(handler, key="fake"):
    settings = Settings(google_api_key=key)
    return create_app(settings, RouteProvider(settings, httpx.Client(transport=httpx.MockTransport(handler))))


def _create(app):
    c = TestClient(app)
    return c, make_journey(c, predefined_route=None)


def test_google_success_decodes_polyline():
    # polyline from Google's documentation: (38.5,-120.2) (40.7,-120.95) (43.252,-126.453)
    enc = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    assert decode_polyline(enc)[0] == (38.5, -120.2)

    def handler(req):
        assert req.headers["X-Goog-Api-Key"] == "fake"
        return httpx.Response(200, json={"routes": [{
            "distanceMeters": 900, "duration": "700s", "polyline": {"encodedPolyline": enc}}]})

    _, j = _create(_provider(handler))
    assert j["route_source"] == "google_routes" and j["route_warning"] is None
    assert j["route_duration_s"] == 700 and len(j["route"]) == 3


def test_google_http_error_falls_back():
    _, j = _create(_provider(lambda r: httpx.Response(403, json={"error": {"message": "API not enabled"}})))
    assert j["route_source"] == "fallback_straight_line"
    assert "403" in j["route_warning"] and "fake" not in j["route_warning"]


def test_google_network_error_falls_back():
    def boom(req):
        raise httpx.ConnectError("down")
    _, j = _create(_provider(boom))
    assert j["route_source"] == "fallback_straight_line"


def test_google_empty_routes_falls_back():
    _, j = _create(_provider(lambda r: httpx.Response(200, json={})))
    assert j["route_source"] == "fallback_straight_line"

