import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import DEFAULT_PERSON  # noqa: E402
from app.geo import offset_point  # noqa: E402
from app.main import create_app  # noqa: E402

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
HOME = (45.5048, -73.5772)
SHOP = (45.5088, -73.5697)
ROUTE0 = HOME  # first point on the predefined route


def iso(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def client():
    return TestClient(create_app(Settings(google_api_key=None, route_mode="offline")))


@pytest.fixture
def journey(client):
    return make_journey(client)


def sign_in(client, email="test.account@example.com"):
    """Give this test client an app session without running Google OAuth."""
    client.app.state.google.read_session = lambda token: {"person_key": DEFAULT_PERSON, "email": email}
    return client


def make_journey(client, **over):
    body = {
        "user_name": "Margaret",
        "start": {"name": "Home", "latitude": HOME[0], "longitude": HOME[1]},
        "destination": {"name": "Tim Hortons", "latitude": SHOP[0], "longitude": SHOP[1]},
        "expected_arrival": iso(15),
        "started_at": iso(0),
        "predefined_route": "tim_hortons_demo",
    }
    body.update(over)
    r = client.post("/api/journeys", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def send(client, jid, lat, lng, minute):
    r = client.post(f"/api/journeys/{jid}/location",
                    json={"latitude": lat, "longitude": lng, "timestamp": iso(minute)})
    assert r.status_code == 200, r.text
    return r.json()


def far_off_route(north=0.0, east=-300.0):
    """A point ~300 m west of the start (well away from the NE-heading route)."""
    return offset_point(HOME[0], HOME[1], north, east)
