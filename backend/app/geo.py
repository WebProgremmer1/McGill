"""GPS maths: turning latitude/longitude into metres.

The idea (see README, "How metres are worked out"):
  * 1 degree of latitude (north-south) is always about 111,320 m.
  * 1 degree of longitude (east-west) is shorter the further you are from the
    equator, so we multiply by cos(latitude). In Montreal that is about 78,000 m.
  * Once two points are in metres (x = east, y = north) we use Pythagoras.

This "flat map" trick is accurate to well under 1 m over a few kilometres,
which is plenty for a walk across a city.

Every function here takes points that have .latitude and .longitude
(Place, Coordinates and TrackPoint all do).
"""
from __future__ import annotations

import math

METRES_PER_DEGREE = 111_320  # length of 1 degree of latitude


def metres_from(origin, p) -> tuple[float, float]:
    """Where p is compared to origin, in metres: (east, north)."""
    east = (p.longitude - origin.longitude) * METRES_PER_DEGREE * math.cos(math.radians(origin.latitude))
    north = (p.latitude - origin.latitude) * METRES_PER_DEGREE
    return east, north


def distance_m(a, b) -> float:
    """Straight-line distance between two points, in metres."""
    east, north = metres_from(a, b)
    return math.hypot(east, north)  # Pythagoras: sqrt(east^2 + north^2)


def distance_to_segment_m(p, a, b) -> float:
    """Distance from point p to the closest spot on the straight line a -> b."""
    # Put p at (0, 0) and express a and b in metres around it.
    ax, ay = metres_from(p, a)
    bx, by = metres_from(p, b)
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:  # a and b are the same point
        return math.hypot(ax, ay)
    # t says how far along a -> b the closest spot is (0 = at a, 1 = at b).
    t = -(ax * dx + ay * dy) / length_squared
    t = max(0.0, min(1.0, t))  # stay on the segment, not past its ends
    closest_x, closest_y = ax + t * dx, ay + t * dy
    return math.hypot(closest_x, closest_y)


def distance_to_route_m(p, route) -> float:
    """How far p is from the route: the closest of all the route's segments."""
    if len(route) == 1:
        return distance_m(p, route[0])
    return min(distance_to_segment_m(p, a, b) for a, b in zip(route, route[1:]))


def offset_point(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Move a point by some metres north and east (used by the demo and tests)."""
    new_lat = lat + north_m / METRES_PER_DEGREE
    new_lon = lon + east_m / (METRES_PER_DEGREE * math.cos(math.radians(lat)))
    return new_lat, new_lon


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode the compressed route string Google sends back into (lat, lon) pairs.
    Format: https://developers.google.com/maps/documentation/utilities/polylinealgorithm"""
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
