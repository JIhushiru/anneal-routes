"""Great-circle distances.

Haversine is the default distance for OptiRoute: stops are dropped on a map without
any road network attached, so the geodesic is the honest lower bound on travel
distance. The optional OSRM mode (see ``osrm.py``) replaces this matrix with real
road distances.
"""

from __future__ import annotations

import math
from typing import Sequence

EARTH_RADIUS_KM = 6371.0088  # IUGG mean Earth radius


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in kilometres.

    Uses the haversine form, which is numerically stable for the small angular
    separations typical of intra-city routing (unlike the spherical law of
    cosines, which loses precision below ~1 km).

        hav(theta) = sin^2(dphi/2) + cos(phi1) * cos(phi2) * sin^2(dlambda/2)
        d = 2 R asin(sqrt(hav))
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def haversine_matrix(coords: Sequence[tuple[float, float]]) -> list[list[float]]:
    """Symmetric distance matrix (km) for a list of (lat, lon) points."""
    n = len(coords)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        lat_i, lon_i = coords[i]
        for j in range(i + 1, n):
            d = haversine_km(lat_i, lon_i, coords[j][0], coords[j][1])
            matrix[i][j] = d
            matrix[j][i] = d
    return matrix
