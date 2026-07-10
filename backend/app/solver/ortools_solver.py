"""OR-Tools CVRPTW baseline (RoutingModel + guided local search).

This wraps Google OR-Tools as the reference solver. Costs reported to the rest of
the app are ALWAYS recomputed with our own evaluator (evaluate.py) on the routes
OR-Tools returns — never taken from OR-Tools' internal objective — so SA,
nearest-neighbor, and OR-Tools are compared on the identical cost function.

Modeling notes
--------------
* Distances are scaled to integer meters, times to integer seconds (OR-Tools is
  integer-only; meters/seconds keep rounding error far below solution deltas).
* Time windows are HARD constraints here (contrast: soft penalties in SA). To
  keep the model solvable on over-constrained instances, every stop gets a
  disjunction with a large drop penalty — OR-Tools will drop a visit rather than
  return nothing, and we surface dropped stops as ``unassigned``.
* The time dimension's transit includes the service time of the departure node,
  and slack (waiting) is unbounded, matching evaluate.py's wait-if-early rule.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .evaluate import evaluate_solution
from .model import RoutingProblem, Solution

METERS = 1000  # km -> m
SECONDS = 60  # min -> s
DEMAND_SCALE = 1000  # fractional demands -> integer units
DROP_PENALTY = 100_000_000  # meters; >> any tour, so drops happen only when forced


@dataclass(frozen=True)
class ORToolsEvent:
    solution_index: int
    best_cost: float
    best_distance_km: float
    routes: Solution
    elapsed_ms: float


@dataclass(frozen=True)
class ORToolsResult:
    best: Solution
    best_cost: float
    best_distance_km: float
    solutions_seen: int
    unassigned: list[int]  # node indices dropped by the disjunctions
    runtime_ms: float


def solve_ortools(
    p: RoutingProblem,
    time_limit_s: float = 10.0,
    on_solution: Optional[Callable[[ORToolsEvent], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> ORToolsResult:
    """``should_stop`` is polled at every solution event; when it turns true the
    CP search is asked to finish early, returning the best solution found so far
    (this is how a client cancel reaches an in-flight OR-Tools run)."""
    started = time.perf_counter()

    manager = pywrapcp.RoutingIndexManager(p.n + 1, p.vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    dist_m = [[round(d * METERS) for d in row] for row in p.dist_km]
    # Transit for the time dimension: travel(i -> j) + service(i).
    transit_s = [
        [round(p.time_min[i][j] * SECONDS + p.service_min[i] * SECONDS) for j in range(p.n + 1)]
        for i in range(p.n + 1)
    ]

    def distance_cb(from_index: int, to_index: int) -> int:
        return dist_m[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_index = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

    def demand_cb(from_index: int) -> int:
        return round(p.demand[manager.IndexToNode(from_index)] * DEMAND_SCALE)

    demand_index = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(
        demand_index,
        0,  # no slack for load
        [round(p.capacity * DEMAND_SCALE)] * p.vehicles,
        True,  # start empty
        "Capacity",
    )

    def time_cb(from_index: int, to_index: int) -> int:
        return transit_s[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    time_index = routing.RegisterTransitCallback(time_cb)
    # The horizon must dominate every finite window BOUND — including the start of
    # an open-ended "not before X" window, where the vehicle may have to sit and
    # wait until X before doing any more driving. Deriving it from window ends
    # alone made SetRange(start, horizon) invert for such stops -> "CP Solver fail".
    finite_bounds = [b for w in p.tw if w is not None for b in w if b != float("inf")]
    horizon_s = round(
        (max(finite_bounds, default=0.0) + sum(sum(r) for r in p.time_min) + sum(p.service_min)) * SECONDS
    ) + 1
    routing.AddDimension(time_index, horizon_s, horizon_s, True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    for node in range(1, p.n + 1):
        window = p.tw[node]
        if window is not None:
            end = horizon_s if window[1] == float("inf") else round(window[1] * SECONDS)
            time_dim.CumulVar(manager.NodeToIndex(node)).SetRange(round(window[0] * SECONDS), end)
        # Allow dropping any stop at a prohibitive price instead of failing outright.
        routing.AddDisjunction([manager.NodeToIndex(node)], DROP_PENALTY)

    solutions_seen = 0

    def _extract_bound_routes() -> Optional[Solution]:
        """Read routes off the NextVar values (bound at solution callbacks)."""
        try:
            routes: Solution = []
            for v in range(p.vehicles):
                index = routing.Start(v)
                route: list[int] = []
                while not routing.IsEnd(index):
                    node = manager.IndexToNode(index)
                    if node != 0:
                        route.append(node)
                    index = routing.NextVar(index).Value()
                routes.append(route)
            return routes
        except Exception:
            return None  # var not bound mid-search; skip this event

    def _at_solution() -> None:
        nonlocal solutions_seen
        solutions_seen += 1
        if should_stop is not None and should_stop():
            try:
                routing.solver().FinishCurrentSearch()
            except Exception:
                pass  # cancellation is best-effort; the time limit still bounds the run
        if on_solution is None:
            return
        routes = _extract_bound_routes()
        if routes is None:
            return
        evals = evaluate_solution(routes, p)
        on_solution(
            ORToolsEvent(
                solution_index=solutions_seen,
                best_cost=sum(e.penalized_cost for e in evals),
                best_distance_km=sum(e.distance_km for e in evals),
                routes=routes,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        )

    routing.AddAtSolutionCallback(_at_solution)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))

    assignment = routing.SolveWithParameters(params)
    runtime_ms = (time.perf_counter() - started) * 1000

    if assignment is None:
        # No solution at all (should not happen with disjunctions, but be explicit).
        empty: Solution = [[] for _ in range(p.vehicles)]
        return ORToolsResult(empty, float("inf"), 0.0, solutions_seen, list(range(1, p.n + 1)), runtime_ms)

    routes: Solution = []
    for v in range(p.vehicles):
        index = routing.Start(v)
        route: list[int] = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:
                route.append(node)
            index = assignment.Value(routing.NextVar(index))
        routes.append(route)

    assigned = {node for route in routes for node in route}
    unassigned = [node for node in range(1, p.n + 1) if node not in assigned]

    evals = evaluate_solution(routes, p)
    return ORToolsResult(
        best=routes,
        best_cost=sum(e.penalized_cost for e in evals),
        best_distance_km=sum(e.distance_km for e in evals),
        solutions_seen=solutions_seen,
        unassigned=unassigned,
        runtime_ms=runtime_ms,
    )
