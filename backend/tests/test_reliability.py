"""GPS reliability, data freshness, progress-aware loops and the stateless endpoints."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.geo import offset_point
from app.main import create_app
from app.risk import RiskConfig

from conftest import HOME, SHOP, far_off_route, iso, make_journey

SIM_DIR = Path(__file__).resolve().parent.parent / "simulations"


def codes(result):
    return [r["code"] for r in result["risk"]["reasons"]]


def send(client, jid, lat, lng, minute, accuracy=None):
    body = {"latitude": lat, "longitude": lng, "timestamp": iso(minute)}
    if accuracy is not None:
        body["accuracy_m"] = accuracy
    r = client.post(f"/api/journeys/{jid}/location", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def on_route(journey, i):
    p = journey["route"][i]
    return p["latitude"], p["longitude"]


# ---------------------------------------------------------------- GPS filtering
def test_single_gps_spike_is_ignored(client, journey):
    jid = journey["id"]
    send(client, jid, *on_route(journey, 0), 0)
    send(client, jid, *on_route(journey, 1), 2)
    spike = offset_point(*on_route(journey, 1), 0, -800)       # 800 m in 30 s: impossible on foot
    res = send(client, jid, *spike, 2.5)
    assert res["risk"]["score"] == 0 and res["risk"]["discarded_readings"] == 1
    for minute in (3, 3.5, 4):
        res = send(client, jid, *on_route(journey, 1), minute)
    assert "off_route" not in codes(res)
    assert res["risk"]["accepted_readings"] == 5 and res["risk"]["data_status"] == "ok"


def test_inaccurate_readings_are_discarded(client, journey):
    off = far_off_route()
    for minute in range(3):
        res = send(client, journey["id"], *off, minute, accuracy=80)
    assert res["risk"]["discarded_readings"] == 3 and res["risk"]["accepted_readings"] == 0
    assert "off_route" not in codes(res)
    assert res["risk"]["data_status"] == "insufficient_or_stale"


def test_gps_error_is_subtracted_from_route_distance(client):
    # ~130 m from the route: off route with a sharp fix, not with a 40 m fuzzy one
    lat, lng = offset_point(HOME[0], HOME[1], 78, -104)
    fuzzy = make_journey(client)
    for m in range(3):
        res = send(client, fuzzy["id"], lat, lng, m, accuracy=40)
    assert 120 < res["risk"]["distance_from_route_m"] < 140
    assert "off_route" not in codes(res)
    sharp = make_journey(client)
    for m in range(3):
        res = send(client, sharp["id"], lat, lng, m, accuracy=5)
    assert codes(res) == ["off_route"]


def test_repeated_jumps_to_the_same_spot_are_trusted(client, journey):
    # e.g. the very first fix was wrong: after 3 consistent readings elsewhere we move on
    jid = journey["id"]
    send(client, jid, *HOME, 0)
    elsewhere = offset_point(HOME[0], HOME[1], 2000, 0)
    send(client, jid, *elsewhere, 1)
    send(client, jid, *elsewhere, 2)
    res = send(client, jid, *elsewhere, 3)
    assert res["risk"]["discarded_readings"] == 2
    assert res["risk"]["accepted_readings"] == 2
    assert res["risk"]["distance_from_route_m"] > 1000


def test_long_gap_breaks_stationary_evidence(client, journey):
    p = on_route(journey, 1)
    send(client, journey["id"], *p, 0)
    res = send(client, journey["id"], *p, 7)          # 7 min of silence, not 7 min of evidence
    assert "stationary" not in codes(res)


def test_location_update_stores_accuracy_and_new_journey_has_no_data(client):
    j = make_journey(client)
    assert j["risk"]["data_status"] == "insufficient_or_stale"
    send(client, j["id"], *HOME, 0, accuracy=12.5)
    got = client.get(f"/api/journeys/{j['id']}").json()
    assert got["latest_location"]["accuracy_m"] == 12.5
    assert client.post(f"/api/journeys/{j['id']}/location",
                       json={"latitude": HOME[0], "longitude": HOME[1], "accuracy_m": -1}).status_code == 422


# ---------------------------------------------------------------- loops + progress
def test_loop_stops_counting_once_she_heads_to_the_destination(client, journey):
    a = far_off_route(0, -300)
    b = offset_point(*a, 0, 70)
    c = offset_point(*b, 70, 0)
    d = offset_point(*a, 70, 0)
    for i, p in enumerate([a, b, c, d, a, b, c]):
        res = send(client, journey["id"], *p, i)
    assert "repeated_revisits" in codes(res)
    for i, east in enumerate((80, 160), start=7):     # walks east, towards Tim Hortons
        res = send(client, journey["id"], *offset_point(*c, 0, east), i)
    assert "repeated_revisits" not in codes(res)


# ---------------------------------------------------------------- config
def test_risk_config_overrides_thresholds():
    strict = TestClient(create_app(Settings(route_mode="offline"), risk_config=RiskConfig(off_route_updates=1)))
    j = make_journey(strict)
    res = send(strict, j["id"], *far_off_route(), 0)
    assert codes(res) == ["off_route"]
    with pytest.raises(ValueError):
        RiskConfig(max_speed_mps=0)
    with pytest.raises(ValueError):
        RiskConfig(medium_min=70, high_min=60)


# ---------------------------------------------------------------- stateless endpoints
@pytest.mark.parametrize("name, expected_codes, arrived", [
    ("normal", [], True),
    ("deviation", ["off_route"], False),
    ("repeated_movement", ["repeated_revisits"], False),
])
def test_analyze_journey_simulations(client, name, expected_codes, arrived):
    body = json.loads((SIM_DIR / f"{name}.json").read_text())
    r = client.post("/api/analyze-journey", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["journey_id"] == name
    assert codes(out) == expected_codes
    assert out["risk"]["arrived"] is arrived and out["risk"]["data_status"] == "ok"
    assert out["risk"]["accepted_readings"] == len(body["gps_history"])


def test_analyze_journey_flags_stale_data_but_keeps_lateness(client):
    body = json.loads((SIM_DIR / "deviation.json").read_text())
    last = body["gps_history"][-1]["timestamp"]
    body["now"] = last + 15 * 60                 # phone silent for 15 minutes
    body["expected_arrival"] = last - 5 * 60
    out = client.post("/api/analyze-journey", json=body).json()
    assert out["risk"]["data_status"] == "insufficient_or_stale"
    assert codes(out) == ["late_arrival"]       # movement rules need fresh GPS; lateness doesn't


def test_analyze_journey_accepts_iso_and_objects_and_validates_order(client):
    body = {
        "gps_history": [
            {"latitude": HOME[0], "longitude": HOME[1], "timestamp": iso(1), "accuracy_meters": 5},
            {"latitude": HOME[0], "longitude": HOME[1], "timestamp": iso(0), "accuracy_meters": 5},
        ],
        "expected_route": [{"latitude": HOME[0], "longitude": HOME[1]}, list(SHOP)],
    }
    r = client.post("/api/analyze-journey", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "out_of_order_timestamp"
    body["gps_history"].reverse()
    body["now"] = iso(-5)
    assert client.post("/api/analyze-journey", json=body).json()["error"]["code"] == "invalid_now"
    body["now"] = iso(1)
    assert client.post("/api/analyze-journey", json=body).status_code == 200
    empty = client.post("/api/analyze-journey", json={"expected_route": [list(HOME), list(SHOP)]}).json()
    assert empty["risk"]["data_status"] == "insufficient_or_stale" and empty["risk"]["score"] == 0


def test_expected_route_offline_falls_back(client):
    r = client.post("/api/expected-route", json={"start": list(HOME), "destination": list(SHOP)})
    assert r.status_code == 200
    out = r.json()
    assert out["route_source"] == "fallback_straight_line" and len(out["route"]) == 2
    assert 720 < out["distance_m"] < 750       # ~445 m north and ~585 m east
