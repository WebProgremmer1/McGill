"""Place search for the live map's From / To boxes. No real network calls."""
import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.place_search import PlaceSearch

PHOTON = {"features": [
    {"properties": {"name": "Tim Hortons", "street": "Rue Sainte-Catherine", "housenumber": "1000", "city": "Montreal"},
     "geometry": {"coordinates": [-73.5697, 45.5088]}},
    {"properties": {"name": "Tim Hortons", "city": "Toronto"},  # outside Montreal: dropped
     "geometry": {"coordinates": [-79.38, 43.65]}},
]}
GOOGLE = {"places": [{"displayName": {"text": "McGill University"}, "formattedAddress": "845 Sherbrooke St W, Montreal",
                      "location": {"latitude": 45.5048, "longitude": -73.5772}}]}


def app_with(handler, **settings):
    s = Settings(route_mode="offline", **settings)
    calls = []

    def record(request):
        calls.append(request)
        return handler(request)
    places = PlaceSearch(s, httpx.Client(transport=httpx.MockTransport(record)))
    return TestClient(create_app(s, place_search=places)), calls


def test_uses_google_places_when_the_key_allows_it():
    client, calls = app_with(lambda r: httpx.Response(200, json=GOOGLE), google_api_key="server-key")
    r = client.get("/api/places/search", params={"q": "mcgill"})
    assert r.status_code == 200
    assert r.json() == {"source": "google_places", "results": [
        {"name": "McGill University", "address": "845 Sherbrooke St W, Montreal", "latitude": 45.5048, "longitude": -73.5772}]}
    assert calls[0].url.host == "places.googleapis.com"
    assert calls[0].headers["X-Goog-Api-Key"] == "server-key"


def test_falls_back_to_openstreetmap_when_google_refuses_and_stops_asking_google():
    def handler(request):
        if request.url.host == "places.googleapis.com":
            return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED"}})
        return httpx.Response(200, json=PHOTON)
    client, calls = app_with(handler, google_api_key="server-key")
    first = client.get("/api/places/search", params={"q": "tim hortons", "lat": 45.5, "lng": -73.57}).json()
    assert first["source"] == "openstreetmap"
    assert first["results"] == [{"name": "Tim Hortons", "address": "1000 Rue Sainte-Catherine, Montreal",
                                 "latitude": 45.5088, "longitude": -73.5697}]
    assert calls[1].url.params["lat"] == "45.5"
    client.get("/api/places/search", params={"q": "mcgill"})
    assert [c.url.host for c in calls] == ["places.googleapis.com", "photon.komoot.io", "photon.komoot.io"]


def test_repeated_queries_are_cached():
    client, calls = app_with(lambda r: httpx.Response(200, json=PHOTON))
    client.get("/api/places/search", params={"q": "Tim  Hortons"})
    client.get("/api/places/search", params={"q": "tim hortons"})
    assert len(calls) == 1


def test_reports_when_no_search_is_available():
    client, calls = app_with(lambda r: httpx.Response(500), place_search_fallback=False)
    r = client.get("/api/places/search", params={"q": "tim hortons"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "place_search_unavailable"
    assert calls == []


def test_rejects_too_short_queries():
    client, _ = app_with(lambda r: httpx.Response(200, json=PHOTON))
    assert client.get("/api/places/search", params={"q": "t"}).status_code == 422


def test_reverse_names_a_picked_spot():
    reverse = {"features": [{"properties": {"housenumber": "845", "street": "Rue Sherbrooke Ouest", "city": "Montreal"},
                             "geometry": {"coordinates": [-73.5772, 45.5048]}}]}
    client, calls = app_with(lambda r: httpx.Response(200, json=reverse))
    r = client.get("/api/places/reverse", params={"lat": 45.5048, "lng": -73.5772})
    assert r.json() == {"name": "845 Rue Sherbrooke Ouest", "address": "Montreal"}
    assert calls[0].url.path == "/reverse"


def test_reverse_returns_no_name_when_lookup_fails():
    client, _ = app_with(lambda r: httpx.Response(503))
    assert client.get("/api/places/reverse", params={"lat": 45.5, "lng": -73.57}).json() == {"name": None, "address": ""}
