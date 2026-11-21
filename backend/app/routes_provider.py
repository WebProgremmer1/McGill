"""Walking-route lookup: Google Routes API, predefined offline routes, or a fallback.

The route is calculated ONCE, when the journey is created. Google failures never
crash the API: we fall back to a straight line and attach a warning."""
from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass

import httpx
import truststore

from .config import Settings
from .errors import ApiError
from .geo import decode_polyline, distance_m
from .models import Coordinates, Place

log = logging.getLogger("routes")

GOOGLE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Trust the same HTTPS certificates as Windows / your browser. Without this, antivirus
# that inspects HTTPS (e.g. Norton Web Shield) makes every call to Google fail.
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

# Fictional demo route (McGill area, Montreal): home -> "Tim Hortons".
PREDEFINED_ROUTES: dict[str, list[tuple[float, float]]] = {
    "tim_hortons_demo": [
        (45.5048, -73.5772),
        (45.5060, -73.5754),
        (45.5072, -73.5736),
        (45.5080, -73.5717),
        (45.5088, -73.5697),
    ],
}


@dataclass
class RouteResult:
    points: list[Coordinates]
    source: str
    warning: str | None = None
    distance_m: float | None = None
    duration_s: int | None = None


def _coords(pairs) -> list[Coordinates]:
    return [Coordinates(latitude=a, longitude=b) for a, b in pairs]


class RouteProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self._client = client

    def resolve(
        self,
        start: Place,
        dest: Place,
        client_route: list[Coordinates] | None,
        predefined: str | None,
    ) -> RouteResult:
        if client_route:
            return RouteResult(client_route, "client")
        if predefined:
            if predefined not in PREDEFINED_ROUTES:
                raise ApiError(
                    422,
                    "unknown_predefined_route",
                    f"Unknown predefined_route '{predefined}'.",
                    {"available": sorted(PREDEFINED_ROUTES)},
                )
            pts = _coords(PREDEFINED_ROUTES[predefined])
            return RouteResult(pts, "predefined")
        if not self.settings.google_enabled:
            reason = (
                "ROUTE_MODE=offline"
                if self.settings.route_mode == "offline"
                else "GOOGLE_MAPS_API_KEY is not set"
            )
            return self._fallback(start, dest, f"{reason}; using a straight-line route.")
        return self._google(start, dest)

    # ------------------------------------------------------------------
    def _fallback(self, start: Place, dest: Place, warning: str) -> RouteResult:
        pts = [
            Coordinates(latitude=start.latitude, longitude=start.longitude),
            Coordinates(latitude=dest.latitude, longitude=dest.longitude),
        ]
        dist = distance_m(start, dest)
        return RouteResult(pts, "fallback_straight_line", warning, dist, int(dist / 1.3))

    def _google(self, start: Place, dest: Place) -> RouteResult:
        body = {
            "origin": {"location": {"latLng": {"latitude": start.latitude, "longitude": start.longitude}}},
            "destination": {"location": {"latLng": {"latitude": dest.latitude, "longitude": dest.longitude}}},
            "travelMode": "WALK",
        }
        headers = {
            "X-Goog-Api-Key": self.settings.google_api_key or "",
            "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
            "Content-Type": "application/json",
        }
        try:
            client = self._client or httpx.Client(timeout=8.0, verify=SSL_CONTEXT)
            resp = client.post(GOOGLE_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("Google Routes request failed: %s", type(exc).__name__)
            return self._fallback(start, dest, f"Google Routes unreachable ({type(exc).__name__}); using a straight-line route.")
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                msg = ""
            log.warning("Google Routes HTTP %s", resp.status_code)
            return self._fallback(
                start, dest,
                f"Google Routes returned HTTP {resp.status_code} ({msg[:150]}); using a straight-line route.",
            )
        try:
            route = resp.json()["routes"][0]
            pts = _coords(decode_polyline(route["polyline"]["encodedPolyline"]))
            if len(pts) < 2:
                raise ValueError("polyline too short")
            secs = int(str(route.get("duration", "0s")).rstrip("s") or 0)
            return RouteResult(pts, "google_routes", None, route.get("distanceMeters"), secs)
        except (KeyError, IndexError, ValueError, TypeError):
            return self._fallback(start, dest, "Google Routes found no walking route; using a straight-line route.")
