"""OSRM table-service client with an on-disk response cache.

Behind the "real road distances" toggle. Uses the public demo server's
``/table`` endpoint to fetch a full NxN driving distance/duration matrix in one
request. Responses are cached by a hash of the (rounded) coordinate list so
repeated solves of the same instance never re-hit the network — the demo server
is a shared courtesy resource.

The public server caps table requests at 100 coordinates, comfortably above the
app's 50-stop scenarios.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence

import httpx

OSRM_BASE = "https://router.project-osrm.org"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".osrm_cache"
# 5 decimal places ~ 1.1 m: dragging a marker imperceptibly should not bust the cache.
COORD_PRECISION = 5


class OSRMError(RuntimeError):
    """Raised when the OSRM server is unreachable or returns a non-Ok response."""


def _cache_key(coords: Sequence[tuple[float, float]]) -> str:
    canon = ";".join(f"{lat:.{COORD_PRECISION}f},{lon:.{COORD_PRECISION}f}" for lat, lon in coords)
    return hashlib.sha256(canon.encode()).hexdigest()[:32]


def fetch_osrm_matrices(
    coords: Sequence[tuple[float, float]], timeout_s: float = 20.0
) -> tuple[list[list[float]], list[list[float]]]:
    """Return (distance_km, duration_min) matrices for (lat, lon) points.

    Raises OSRMError with a user-presentable message on any failure; the caller
    surfaces it over the WebSocket so the user can fall back to haversine.
    """
    if len(coords) > 100:
        raise OSRMError("OSRM public server supports at most 100 locations per matrix")

    key = _cache_key(coords)
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            return cached["dist_km"], cached["time_min"]
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            cache_file.unlink(missing_ok=True)  # corrupted/truncated cache: refetch

    # OSRM wants lon,lat order.
    path = ";".join(f"{lon:.{COORD_PRECISION}f},{lat:.{COORD_PRECISION}f}" for lat, lon in coords)
    url = f"{OSRM_BASE}/table/v1/driving/{path}"
    try:
        resp = httpx.get(url, params={"annotations": "distance,duration"}, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise OSRMError(f"OSRM request failed ({exc}); switch back to haversine distances") from exc
    except ValueError as exc:  # 200 with a non-JSON body (proxy error page, etc.)
        raise OSRMError("OSRM returned a malformed response; switch back to haversine distances") from exc

    if not isinstance(data, dict) or data.get("code") != "Ok":
        code = data.get("code") if isinstance(data, dict) else "malformed"
        msg = data.get("message", "unknown error") if isinstance(data, dict) else ""
        raise OSRMError(f"OSRM returned {code}: {msg}")

    # Unroutable pairs come back as null; substitute a large-but-finite distance so
    # the solvers steer around them instead of crashing.
    def _clean(matrix: list[list[float | None]], scale: float, fallback: float) -> list[list[float]]:
        return [[(v * scale if v is not None else fallback) for v in row] for row in matrix]

    try:
        raw_dist, raw_time = data["distances"], data["durations"]
        unroutable = any(v is None for row in raw_dist for v in row) or any(
            v is None for row in raw_time for v in row
        )
        dist_km = _clean(raw_dist, 1 / 1000, fallback=10_000.0)
        time_min = _clean(raw_time, 1 / 60, fallback=100_000.0)
    except (KeyError, TypeError) as exc:
        raise OSRMError("OSRM response is missing its distance/duration matrices") from exc

    # Don't bake sentinel values into the cache: an unroutable pair may become
    # routable after an OSM data fix, and a poisoned cache would hide it forever.
    if not unroutable:
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps({"dist_km": dist_km, "time_min": time_min}))
    return dist_km, time_min
