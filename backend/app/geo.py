"""Small GPS maths helpers (no external libraries)."""
from __future__ import annotations

import math
from typing import Sequence

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    """Project to a flat local grid (metres). Accurate enough for city-scale distances."""
    x = math.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
    y = math.radians(lat) * EARTH_RADIUS_M
    return x, y


def point_to_segment_m(plat, plon, alat, alon, blat, blon) -> float:
    px, py = _xy(plat, plon, plat)
    ax, ay = _xy(alat, alon, plat)
    bx, by = _xy(blat, blon, plat)
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_route_m(lat: float, lon: float, route: Sequence) -> float:
    """Shortest distance from a point to a polyline (items need .latitude/.longitude)."""
    if not route:
        return math.inf
    if len(route) == 1:
        return haversine_m(lat, lon, route[0].latitude, route[0].longitude)
    return min(
        point_to_segment_m(
            lat, lon, a.latitude, a.longitude, b.latitude, b.longitude
        )
        for a, b in zip(route, route[1:])
    )


def offset_point(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Move a point by metres north/east."""
    dlat = math.degrees(north_m / EARTH_RADIUS_M)
    dlon = math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def route_length_m(route: Sequence) -> float:
    return sum(
        haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        for a, b in zip(route, route[1:])
    )


def interpolate_route(route: Sequence, fraction: float) -> tuple[float, float]:
    """Point at `fraction` (0..1) of the way along the polyline."""
    fraction = max(0.0, min(1.0, fraction))
    total = route_length_m(route)
    target = total * fraction
    walked = 0.0
    for a, b in zip(route, route[1:]):
        seg = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
        if walked + seg >= target and seg > 0:
            t = (target - walked) / seg
            return (
                a.latitude + (b.latitude - a.latitude) * t,
                a.longitude + (b.longitude - a.longitude) * t,
            )
        walked += seg
    last = route[-1]
    return last.latitude, last.longitude


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline into (lat, lon) pairs."""
    coords: list[tuple[float, float]] = []
    index = lat = lon = 0
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / 1e5, lon / 1e5))
    return coords
