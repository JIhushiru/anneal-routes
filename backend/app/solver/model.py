"""Internal solver representation of a CVRPTW instance.

The Pydantic ``Problem`` (schemas.py) is the wire format; solvers work on this
flat, index-based view instead:

* Node ``0`` is the depot; nodes ``1..n`` are stops, where node ``i`` maps to
  ``problem.stops[i - 1]``.
* A ``Solution`` is ``list[list[int]]`` — one list of node indices per vehicle,
  depot excluded. Empty routes are allowed (an unused vehicle).

Keeping the matrix and per-node arrays precomputed means every solver (SA,
nearest-neighbor, OR-Tools) prices the exact same instance, so their costs are
directly comparable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..schemas import Problem
from .distance import haversine_matrix

# One vehicle's visit order (node indices, depot excluded), and a full solution.
Route = list[int]
Solution = list[Route]


@dataclass(frozen=True)
class RoutingProblem:
    n: int  # number of stops (nodes are 0..n, 0 = depot)
    dist_km: list[list[float]]  # (n+1) x (n+1)
    time_min: list[list[float]]  # travel time in minutes, derived from dist / speed
    demand: list[float]  # index 0 (depot) is 0.0
    tw: list[Optional[tuple[float, float]]]  # per-node window, None = unconstrained
    service_min: list[float]  # index 0 (depot) is 0.0
    vehicles: int
    capacity: float
    stop_ids: list[int] = field(default_factory=list)  # node index -> client stop id (index 0 unused)
    # Per-node candidate lists: the k nearest OTHER stops (depot excluded), by
    # distance. Used to bias inter-route move proposals toward geographically
    # plausible targets; empty tuple = fall back to uniform proposals.
    neighbors: tuple[tuple[int, ...], ...] = ()

    def node_of_stop_id(self, stop_id: int) -> int:
        return self.stop_ids.index(stop_id)


def build_routing_problem(
    problem: Problem,
    dist_km: Optional[list[list[float]]] = None,
    time_min: Optional[list[list[float]]] = None,
) -> RoutingProblem:
    """Flatten a wire-format ``Problem`` into matrices and per-node arrays.

    ``dist_km``/``time_min`` override the default haversine matrix and the
    speed-derived travel times — this is how OSRM road distances and real driving
    durations are injected. Node 0 is the depot in both matrices.
    """
    coords = [(problem.depot.lat, problem.depot.lon)] + [(s.lat, s.lon) for s in problem.stops]
    dist = dist_km if dist_km is not None else haversine_matrix(coords)
    if time_min is None:
        minutes_per_km = 60.0 / problem.speed_kmh
        time = [[d * minutes_per_km for d in row] for row in dist]
    else:
        time = time_min

    tw: list[Optional[tuple[float, float]]] = [None]
    for s in problem.stops:
        if s.tw_start is None and s.tw_end is None:
            tw.append(None)
        else:
            # A half-open window is closed with a permissive bound.
            tw.append((s.tw_start or 0.0, s.tw_end if s.tw_end is not None else float("inf")))

    n = len(problem.stops)
    k = min(10, n - 1)
    neighbors: list[tuple[int, ...]] = [()]  # depot has no candidate list
    for i in range(1, n + 1):
        ranked = sorted((j for j in range(1, n + 1) if j != i), key=lambda j: dist[i][j])
        neighbors.append(tuple(ranked[:k]))

    return RoutingProblem(
        n=n,
        dist_km=dist,
        time_min=time,
        demand=[0.0] + [s.demand for s in problem.stops],
        tw=tw,
        service_min=[0.0] + [s.service_time for s in problem.stops],
        vehicles=problem.fleet.count,
        capacity=problem.fleet.capacity,
        stop_ids=[0] + [s.id for s in problem.stops],
        neighbors=tuple(neighbors),
    )


def routes_to_stop_ids(solution: Solution, p: RoutingProblem) -> list[list[int]]:
    """Map internal node indices back to client stop ids for the wire format."""
    return [[p.stop_ids[node] for node in route] for route in solution]
