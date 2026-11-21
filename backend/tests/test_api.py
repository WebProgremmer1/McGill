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


def test_route_deviation(client, journey):
    res = send(client, journey["id"], *far_off_route(), 3)
    assert codes(res) == ["off_route"]
    assert res["risk"]["score"] == 25 and res["risk"]["level"] == "low"
    # score is recalculated, not accumulated: returning to the route drops it back
    res = send(client, journey["id"], *HOME, 4)
    assert res["risk"]["score"] == 0
    res = send(client, journey["id"], *far_off_route(), 5)
    assert res["risk"]["score"] == 25


SHOP_ZONE = {"name": "Tim Hortons", "latitude": SHOP[0], "longitude": SHOP[1], "radius_m": 75}
HOME_ZONE = {"name": "Home", "latitude": HOME[0], "longitude": HOME[1], "radius_m": 75}


def test_safe_zone_exit_after_arriving(client):
    j = make_journey(client, safe_zones=[HOME_ZONE, SHOP_ZONE])
    res = send(client, j["id"], *SHOP, 1)          # arrives inside the zone
    assert "left_safe_zone" not in codes(res)
    lat, lng = offset_point(SHOP[0], SHOP[1], 0, 300)
    res = send(client, j["id"], lat, lng, 2)       # wanders out
    assert "left_safe_zone" in codes(res)
    res = send(client, j["id"], *SHOP, 3)          # back inside: recalculated
    assert "left_safe_zone" not in codes(res)


def test_leaving_home_zone_never_scores(client):
    j = make_journey(client, safe_zones=[HOME_ZONE, SHOP_ZONE])
    send(client, j["id"], *HOME, 0)
    lat, lng = offset_point(HOME[0], HOME[1], 0, 400)
    res = send(client, j["id"], lat, lng, 1)
    assert "left_safe_zone" not in codes(res)


def test_destination_zone_not_scored_before_arriving(client):
    j = make_journey(client, safe_zones=[SHOP_ZONE])
    send(client, j["id"], *HOME, 0)
    res = send(client, j["id"], *far_off_route(), 1)
    assert "left_safe_zone" not in codes(res)


def test_stationary_detection(client, journey):
    lat, lng = journey["route"][1]["latitude"], journey["route"][1]["longitude"]
    for m in range(0, 6):  # exactly 5 minutes: not yet "more than five"
        res = send(client, journey["id"], lat, lng, m)
    assert "stationary" not in codes(res)
    res = send(client, journey["id"], lat, lng, 6)
    assert "stationary" in codes(res)
    assert res["risk"]["score"] == 15


def test_stationary_at_destination_is_fine(client, journey):
    for m in range(0, 9):
        res = send(client, journey["id"], *SHOP, m)
    assert "stationary" not in codes(res)


def test_loop_detection(client, journey):
    a = far_off_route(0, -300)
    b = offset_point(*a, 0, 70)
    c = offset_point(*b, 70, 0)
    d = offset_point(*a, 70, 0)
    seq = [a, b, c, d, a, b, c, d]
    results = [send(client, journey["id"], *p, i) for i, p in enumerate(seq)]
    assert "repeated_revisits" not in codes(results[5])  # 2 revisits so far
    assert "repeated_revisits" in codes(results[6])      # 3rd revisit


def test_single_turnaround_is_not_a_loop(client, journey):
    pts = [offset_point(*HOME, 0, 40 * i) for i in range(4)]
    for i, p in enumerate(pts + pts[::-1][1:]):
        res = send(client, journey["id"], *p, i)
    assert "repeated_revisits" not in codes(res)


def test_late_arrival(client, journey):
    res = send(client, journey["id"], *HOME, 25)   # 10 min late exactly: not more than 10
    assert "late_arrival" not in codes(res)
    res = send(client, journey["id"], *HOME, 26)
    assert "late_arrival" in codes(res)
    assert res["risk"]["score"] == 20


def test_arriving_late_but_arrived_is_not_flagged(client, journey):
    res = send(client, journey["id"], *SHOP, 30)
    assert "late_arrival" not in codes(res)


def test_score_capped_at_100():
    from app.risk import level_for
    assert level_for(29) == "low" and level_for(30) == "medium"
    assert level_for(59) == "medium" and level_for(60) == "high"


# ---------------------------------------------------------------- escalation
def test_medium_creates_checkin_once(client):
    j = make_journey(client, safe_zones=[SHOP_ZONE])
    send(client, j["id"], *SHOP, 0)
    # off route (25) + left the destination zone (15) = 40 -> medium
    lat, lng = offset_point(SHOP[0], SHOP[1], 0, 1500)
    res = send(client, j["id"], lat, lng, 1)
    assert res["risk"]["level"] == "medium"
    assert res["checkin_created"] and "Tim Hortons" in res["checkin_created"]["message"]
    res2 = send(client, j["id"], lat, lng, 2)
    assert res2["checkin_created"] is None and res2["deduplicated"] is True
    assert len(client.get(f"/api/journeys/{j['id']}/checkins").json()) == 1


def test_answering_checkin(client):
    j = make_journey(client, safe_zones=[SHOP_ZONE])
    send(client, j["id"], *SHOP, 0)
    send(client, j["id"], *offset_point(SHOP[0], SHOP[1], 0, 1500), 1)
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
    # drive to high: off route 25 + stationary 15 + late 20 = 60
    lat, lng = far_off_route()
    for m in range(0, 27):
        res = send(client, j["id"], lat, lng, m)
    assert res["risk"]["level"] == "high"
    alert = client.get("/api/alerts").json()[0]
    ack = client.post(f"/api/alerts/{alert['id']}/acknowledge").json()
    assert ack["acknowledged"] is True
    res = send(client, j["id"], lat, lng, 27)
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
    assert s["first_medium_at_minute"] == 11 and s["first_high_at_minute"] == 18
    assert s["checkins_created"] == 1 and s["alerts_created"] == 1
    assert out["steps"][-1]["score"] == 65  # off route + loops + stationary


def test_demo_endpoint_populates_store(client):
    out = client.post("/api/demo/run").json()
    assert client.get(f"/api/journeys/{out['journey_id']}").json()["risk"]["level"] == "high"
    assert len(client.get(f"/api/journeys/{out['journey_id']}/checkins").json()) == 1


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
