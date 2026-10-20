"""Planar geometry on GPS polygons.

Field boundaries are small (well under a kilometre), so an equirectangular
projection centred on the polygon is accurate to a fraction of a percent, which
is far better than hand-held GPS error. Area then follows from the shoelace formula.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

EARTH_RADIUS_M = 6_371_008.8

# Bangladesh land units
SQM_PER_DECIMAL = 40.4686  # 1 decimal (shotangsho) = 1/100 acre
SQM_PER_BIGHA = 1337.8  # standard (33 decimal) bigha
SQM_PER_ACRE = 4046.86
SQM_PER_HECTARE = 10_000.0

Point = tuple[float, float]  # (lat, lng)


class InvalidPolygonError(ValueError):
    pass


def validate_polygon(points: Sequence[Sequence[float]]) -> list[Point]:
    """Return a cleaned ``[(lat, lng), ...]`` ring or raise ``InvalidPolygonError``."""
    if not isinstance(points, (list, tuple)):
        raise InvalidPolygonError("polygon must be a list of [lat, lng] pairs")
    ring: list[Point] = []
    for i, pt in enumerate(points):
        if isinstance(pt, dict):
            pt = (pt.get("lat"), pt.get("lng"))
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise InvalidPolygonError(f"point {i} must be a [lat, lng] pair")
        try:
            lat, lng = float(pt[0]), float(pt[1])
        except (TypeError, ValueError) as exc:
            raise InvalidPolygonError(f"point {i} has non-numeric coordinates") from exc
        if not -90 <= lat <= 90 or not -180 <= lng <= 180:
            raise InvalidPolygonError(f"point {i} is out of range: ({lat}, {lng})")
        ring.append((lat, lng))
    # Drop a closing point that repeats the first one.
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        raise InvalidPolygonError("polygon needs at least 3 distinct points")
    if len(set(ring)) != len(ring):
        raise InvalidPolygonError("polygon has duplicate points")
    return ring


def centroid(points: Sequence[Point]) -> Point:
    lat = sum(p[0] for p in points) / len(points)
    lng = sum(p[1] for p in points) / len(points)
    return lat, lng


def project(points: Sequence[Point], origin: Point | None = None) -> list[tuple[float, float]]:
    """Equirectangular projection to local metres (x east, y north) around ``origin``."""
    origin = origin or centroid(points)
    lat0 = math.radians(origin[0])
    cos_lat0 = math.cos(lat0)
    projected = []
    for lat, lng in points:
        x = EARTH_RADIUS_M * math.radians(lng - origin[1]) * cos_lat0
        y = EARTH_RADIUS_M * math.radians(lat - origin[0])
        projected.append((x, y))
    return projected


def shoelace_area(xy: Sequence[tuple[float, float]]) -> float:
    """Unsigned area of a simple polygon given planar vertices (shoelace formula)."""
    n = len(xy)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def polygon_area_m2(points: Sequence[Sequence[float]]) -> float:
    ring = validate_polygon(points)
    return shoelace_area(project(ring))


def perimeter_m(points: Sequence[Sequence[float]]) -> float:
    xy = project(validate_polygon(points))
    return sum(math.dist(xy[i], xy[(i + 1) % len(xy)]) for i in range(len(xy)))


def m2_to_units(area_m2: float) -> dict[str, float]:
    return {
        "m2": round(area_m2, 1),
        "hectare": round(area_m2 / SQM_PER_HECTARE, 4),
        "acre": round(area_m2 / SQM_PER_ACRE, 4),
        "bigha": round(area_m2 / SQM_PER_BIGHA, 3),
        "decimal": round(area_m2 / SQM_PER_DECIMAL, 1),
    }
