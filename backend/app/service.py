"""Solver orchestration shared by the WebSocket endpoint, the sync REST endpoint,
and the benchmark script: prepare the instance, run the chosen algorithm, emit
progress events, and assemble the wire-format result."""

from __future__ import annotations

import time
from typing import Callable, Optional

from .osrm import fetch_osrm_matrices
from .schemas import (
    Algorithm,
    DistanceMode,
    Problem,
    ProgressEvent,
    RouteResult,
    SolveParams,
    SolveResult,
    TWViolation,
)
from .solver.evaluate import evaluate_solution
from .solver.model import RoutingProblem, Solution, build_routing_problem, routes_to_stop_ids
from .solver.nearest_neighbor import solve_nearest_neighbor
from .solver.ortools_solver import solve_ortools
from .solver.sa import anneal

EmitFn = Callable[[ProgressEvent], None]
ShouldStopFn = Callable[[], bool]


def prepare_problem(problem: Problem) -> RoutingProblem:
    """Build the internal instance, fetching OSRM matrices when toggled on."""
    if problem.distance_mode == DistanceMode.OSRM:
        coords = [(problem.depot.lat, problem.depot.lon)] + [(s.lat, s.lon) for s in problem.stops]
        dist_km, time_min = fetch_osrm_matrices(coords)
        return build_routing_problem(problem, dist_km=dist_km, time_min=time_min)
    return build_routing_problem(problem)


def build_solve_result(
    algorithm: Algorithm,
    solution: Solution,
    p: RoutingProblem,
    runtime_ms: float,
    iterations: Optional[int] = None,
    unassigned_nodes: Optional[list[int]] = None,
) -> SolveResult:
    evals = evaluate_solution(solution, p)
    routes: list[RouteResult] = []
    for vehicle, (route, ev) in enumerate(zip(solution, evals)):
        violations = [
            TWViolation(
                stop_id=p.stop_ids[node],
                arrival_min=round(arrival, 2),
                tw_end=p.tw[node][1],  # type: ignore[index]
                lateness_min=round(arrival - p.tw[node][1], 2),  # type: ignore[index]
            )
            for node, arrival in zip(route, ev.arrivals)
            if p.tw[node] is not None and arrival > p.tw[node][1]  # type: ignore[index]
        ]
        routes.append(
            RouteResult(
                vehicle=vehicle,
                stop_ids=[p.stop_ids[n] for n in route],
                arrivals_min=[round(a, 1) for a in ev.arrivals],
                load=ev.load,
                capacity_excess=ev.cap_excess,
                distance_km=round(ev.distance_km, 3),
                duration_min=round(ev.duration_min, 1),
                tw_violations=violations,
            )
        )
    unassigned = unassigned_nodes or []
    return SolveResult(
        algorithm=algorithm,
        total_distance_km=round(sum(e.distance_km for e in evals), 3),
        cost=round(sum(e.penalized_cost for e in evals), 3),
        runtime_ms=round(runtime_ms, 1),
        iterations=iterations,
        feasible=all(e.feasible for e in evals) and not unassigned,
        unassigned_stop_ids=[p.stop_ids[n] for n in unassigned],
        routes=routes,
    )


def run_solver_streaming(
    problem: Problem,
    params: SolveParams,
    emit: EmitFn,
    should_stop: ShouldStopFn = lambda: False,
) -> SolveResult:
    """Blocking solve with progress callbacks. Run this in a worker thread.

    ``should_stop`` is polled between SA events, so a client cancel takes effect
    within TICK_EVERY iterations. OR-Tools cannot be interrupted mid-search; its
    runtime is bounded by ``params.time_limit_s`` instead.
    """
    p = prepare_problem(problem)
    started = time.perf_counter()

    if params.algorithm == Algorithm.NEAREST_NEIGHBOR:
        solution = solve_nearest_neighbor(p)
        evals = evaluate_solution(solution, p)
        emit(
            ProgressEvent(
                iteration=0,
                temperature=None,
                best_cost=sum(e.penalized_cost for e in evals),
                current_cost=sum(e.penalized_cost for e in evals),
                best_distance_km=sum(e.distance_km for e in evals),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                improved=True,
                routes=routes_to_stop_ids(solution, p),
            )
        )
        return build_solve_result(
            params.algorithm, solution, p, (time.perf_counter() - started) * 1000
        )

    if params.algorithm == Algorithm.OR_TOOLS:
        # The at-solution callback fires for EVERY solution guided local search
        # visits, including deliberate uphill moves — track the incumbent here so
        # the client's "best cost" line is monotone and the map shows the best
        # routes found so far, not whatever GLS is currently exploring.
        best = {"cost": float("inf"), "distance": 0.0, "routes": None}

        def on_solution(ev) -> None:
            improved = ev.best_cost < best["cost"]
            if improved:
                best["cost"] = ev.best_cost
                best["distance"] = ev.best_distance_km
                best["routes"] = ev.routes
            emit(
                ProgressEvent(
                    iteration=ev.solution_index,
                    temperature=None,
                    best_cost=best["cost"],
                    current_cost=ev.best_cost,
                    best_distance_km=best["distance"],
                    elapsed_ms=ev.elapsed_ms,
                    improved=improved,
                    routes=routes_to_stop_ids(best["routes"] or ev.routes, p),
                )
            )

        result = solve_ortools(p, time_limit_s=params.time_limit_s, on_solution=on_solution)
        return build_solve_result(
            params.algorithm,
            result.best,
            p,
            result.runtime_ms,
            iterations=result.solutions_seen,
            unassigned_nodes=result.unassigned,
        )

    # Simulated annealing
    last_event = None
    for event in anneal(p, params.sa, time_limit_s=params.time_limit_s):
        last_event = event
        emit(
            ProgressEvent(
                iteration=event.iteration,
                temperature=event.temperature,
                best_cost=event.best_cost,
                current_cost=event.current_cost,
                best_distance_km=event.best_distance_km,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                improved=event.improved,
                routes=routes_to_stop_ids(event.best_solution, p),
            )
        )
        if should_stop() and not event.final:
            break
    assert last_event is not None
    return build_solve_result(
        params.algorithm,
        last_event.best_solution,
        p,
        (time.perf_counter() - started) * 1000,
        iterations=last_event.iteration,
    )
