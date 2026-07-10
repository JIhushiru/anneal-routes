"""Shared fixtures/helpers: hand-built RoutingProblem instances with exact arithmetic."""

from __future__ import annotations

import math

from app.solver.model import RoutingProblem


def problem_from_matrix(
    dist_km: list[list[float]],
    *,
    speed_kmh: float = 60.0,
    demand: list[float] | None = None,
    tw: list[tuple[float, float] | None] | None = None,
    service_min: list[float] | None = None,
    vehicles: int = 1,
    capacity: float = 100.0,
) -> RoutingProblem:
    """Build a RoutingProblem from an explicit distance matrix (node 0 = depot).

    speed_kmh=60 makes 1 km == 1 minute, so tests can reason in round numbers.
    """
    n = len(dist_km) - 1
    minutes_per_km = 60.0 / speed_kmh
    return RoutingProblem(
        n=n,
        dist_km=dist_km,
        time_min=[[d * minutes_per_km for d in row] for row in dist_km],
        demand=demand or [0.0] * (n + 1),
        tw=tw or [None] * (n + 1),
        service_min=service_min or [0.0] * (n + 1),
        vehicles=vehicles,
        capacity=capacity,
        stop_ids=list(range(n + 1)),
    )


def circle_coords(n: int, center: tuple[float, float] = (14.6, 121.0), radius_deg: float = 0.05):
    """n+1 points on a circle in lat/lon space; index 0 (the depot) included.

    Points in convex position: the unique optimal TSP cycle is the hull order,
    which makes these instances exact ground truth for 2-opt tests.
    """
    cx, cy = center
    return [
        (cx + radius_deg * math.cos(2 * math.pi * k / (n + 1)),
         cy + radius_deg * math.sin(2 * math.pi * k / (n + 1)))
        for k in range(n + 1)
    ]
