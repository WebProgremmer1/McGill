"""Place search for the live map's "From" and "To" boxes.

Google retired the old browser Places Autocomplete for new projects (March 2025), so the
boxes could not suggest anything. The map now asks this backend instead:

1. Google Places API (New) Text Search with the server key, when that API is enabled for it.
2. Otherwise Photon, a free OpenStreetMap search made for search-as-you-type
   (turn off with PLACE_SEARCH_FALLBACK=off).

Results stay inside the Montreal area, like the old autocomplete did."""
from __future__ import annotations

import logging
import ssl
import time
from collections import OrderedDict

import httpx
import truststore

from .config import Settings
from .errors import ApiError

log = logging.getLogger("places")

GOOGLE_URL = "https://places.googleapis.com/v1/places:searchText"
PHOTON_URL = "https://photon.komoot.io/api/"
PHOTON_REVERSE_URL = "https://photon.komoot.io/reverse"
# south, west, north, east
MONTREAL = (45.40, -73.98, 45.71, -73.47)
MAX_RESULTS = 5
# After Google refuses (API not enabled on the key), skip it for a while instead of failing every keystroke.
GOOGLE_RETRY_S = 600
CACHE_SIZE = 200


class PlaceSearch:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self._client = client
        self._google_off_until = 0.0
        self._cache: OrderedDict[tuple, dict] = OrderedDict()

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=6,
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                # A generic client name: no personal details go to outside services.
                headers={"User-Agent": "WalkSafetyDemo/1.0 (place search)"},
            )
        return self._client

    def search(self, query: str, near: tuple[float, float] | None = None) -> dict:
        query = " ".join(query.split())
        key = (query.lower(), round(near[0], 2) if near else None, round(near[1], 2) if near else None)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        result = None
        if self.settings.google_api_key and time.monotonic() >= self._google_off_until:
            result = self._google(query)
        if result is None and self.settings.place_search_fallback:
            result = self._photon(query, near)
        if result is None:
            raise ApiError(
                502, "place_search_unavailable",
                "Place search is unavailable. Use “Pick on map” or drag the labels instead.",
            )

        self._cache[key] = result
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return result

    def reverse(self, lat: float, lng: float) -> dict:
        """A readable name for a spot picked on the map, e.g. "845 Rue Sherbrooke O".
        Returns {"name": None} when nothing is known, so the map keeps its own label."""
        key = ("reverse", round(lat, 5), round(lng, 5))
        if key in self._cache:
            return self._cache[key]
        found = {"name": None, "address": ""}
        if self.settings.place_search_fallback:
            try:
                r = self.client.get(PHOTON_REVERSE_URL, params={"lat": lat, "lon": lng, "lang": "en", "limit": 1})
                r.raise_for_status()
                features = r.json().get("features", [])
            except (httpx.HTTPError, ValueError) as e:
                log.warning("OpenStreetMap reverse lookup failed: %s", type(e).__name__)
                features = []
            if features:
                found = _describe(features[0].get("properties") or {}) or found
        self._cache[key] = found
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return found

    def _google(self, query: str) -> dict | None:
        south, west, north, east = MONTREAL
        try:
            r = self.client.post(
                GOOGLE_URL,
                headers={
                    "X-Goog-Api-Key": self.settings.google_api_key,
                    "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
                },
                json={
                    "textQuery": query, "maxResultCount": MAX_RESULTS, "languageCode": "en", "regionCode": "CA",
                    "locationRestriction": {"rectangle": {
                        "low": {"latitude": south, "longitude": west},
                        "high": {"latitude": north, "longitude": east},
                    }},
                },
            )
        except httpx.HTTPError as e:
            log.warning("Google place search failed: %s", type(e).__name__)
            return None
        if r.status_code in (401, 403):
            log.info("Google Places API (New) is not enabled for this key; using the fallback search.")
            self._google_off_until = time.monotonic() + GOOGLE_RETRY_S
            return None
        if r.status_code != 200:
            log.warning("Google place search returned HTTP %s", r.status_code)
            return None
        places = []
        for p in r.json().get("places", []):
            loc = p.get("location") or {}
            if "latitude" not in loc or "longitude" not in loc:
                continue
            places.append({
                "name": (p.get("displayName") or {}).get("text") or p.get("formattedAddress") or query,
                "address": p.get("formattedAddress") or "",
                "latitude": loc["latitude"], "longitude": loc["longitude"],
            })
        return {"results": places, "source": "google_places"}

    def _photon(self, query: str, near: tuple[float, float] | None) -> dict | None:
        south, west, north, east = MONTREAL
        params = {"q": query, "limit": MAX_RESULTS, "lang": "en", "bbox": f"{west},{south},{east},{north}"}
        if near:
            params["lat"], params["lon"] = near
        try:
            r = self.client.get(PHOTON_URL, params=params)
            r.raise_for_status()
            features = r.json().get("features", [])
        except (httpx.HTTPError, ValueError) as e:
            log.warning("OpenStreetMap place search failed: %s", type(e).__name__)
            return None
        places, seen = [], set()
        for f in features:
            props = f.get("properties") or {}
            coords = (f.get("geometry") or {}).get("coordinates") or []
            if len(coords) != 2:
                continue
            lng, lat = coords
            if not (south <= lat <= north and west <= lng <= east):
                continue
            described = _describe(props) or {"name": query, "address": ""}
            name, address = described["name"], described["address"]
            dedupe = (name, round(lat, 4), round(lng, 4))
            if dedupe in seen:
                continue
            seen.add(dedupe)
            places.append({"name": name, "address": address, "latitude": lat, "longitude": lng})
        return {"results": places, "source": "openstreetmap"}


def _describe(props: dict) -> dict | None:
    """Photon properties -> {"name", "address"}: the place's own name, else its street address."""
    street = " ".join(str(x) for x in (props.get("housenumber"), props.get("street")) if x)
    name = props.get("name") or street
    if not name:
        return None
    address = ", ".join(x for x in (street if street != name else "", props.get("district"), props.get("city")) if x)
    return {"name": name, "address": address}
