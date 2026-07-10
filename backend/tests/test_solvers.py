"""Nearest-neighbor construction and the OR-Tools wrapper."""

from __future__ import annotations

import pytest

from app.scenarios import SCENARIOS
from app.solver.evaluate import is_feasible, solution_distance
from app.solver.model import build_routing_problem
from app.solver.nearest_neighbor import solve_nearest_neighbor
from app.solver.ortools_solver import solve_ortools


def test_nn_assigns_every_stop_exactly_once():
    for key, sc in SCENARIOS.items():
        p = build_routing_problem(sc["problem"])
        sol = solve_nearest_neighbor(p)
        visited = sorted(n for r in sol for n in r)
        assert visited == list(range(1, p.n + 1)), key
        assert len(sol) == p.vehicles


def test_nn_respects_capacity_when_fleet_suffices():
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    sol = solve_nearest_neighbor(p)
    for route in sol:
        assert sum(p.demand[n] for n in route) <= p.capacity + 1e-9


def test_nn_overflows_gracefully_when_fleet_too_small():
    problem = SCENARIOS["laguna"]["problem"].model_copy(deep=True)
    problem.fleet.count = 1
    problem.fleet.capacity = 10  # total demand is far above 10
    p = build_routing_problem(problem)
    sol = solve_nearest_neighbor(p)
    visited = sorted(n for r in sol for n in r)
    assert visited == list(range(1, p.n + 1))  # everything still assigned
    assert not is_feasible(sol, p)  # and the checker reports the overload


def test_ortools_solves_laguna_feasibly():
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    result = solve_ortools(p, time_limit_s=3.0)
    assert result.unassigned == []
    assert is_feasible(result.best, p)
    # OR-Tools with GLS should beat plain greedy on distance.
    nn_dist = solution_distance(solve_nearest_neighbor(p), p)
    assert result.best_distance_km < nn_dist + 1e-9


def test_ortools_streams_solution_events():
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    events = []
    solve_ortools(p, time_limit_s=3.0, on_solution=events.append)
    assert events, "expected at least one at-solution callback"
    assert events[0].routes  # routes were extractable mid-search
    costs = [e.best_cost for e in events]
    assert min(costs) == pytest.approx(costs[-1], rel=0.25)  # improves over time


def test_ortools_handles_open_ended_time_window():
    # Regression: a "not before X" window (tw_end=None) beyond the end-derived
    # horizon used to invert SetRange and crash with "CP Solver fail".
    problem = SCENARIOS["laguna"]["problem"].model_copy(deep=True)
    problem.stops[0].tw_start = 240.0
    problem.stops[0].tw_end = None
    p = build_routing_problem(problem)
    result = solve_ortools(p, time_limit_s=3.0)
    assert result.unassigned == []
    assert is_feasible(result.best, p)  # vehicle simply waits until t=240


def test_ortools_streamed_incumbent_never_prefers_dropped_stops():
    # Regression: an intermediate GLS solution that drops a stop is cheaper on
    # our evaluator (which only prices served stops) and used to lock in as the
    # streamed "best" forever. The streamed best must end where the final,
    # full-coverage result ends.
    from app.schemas import Depot, Fleet, Problem, SolveParams, Stop
    from app.service import run_solver_streaming

    problem = Problem(
        depot=Depot(lat=14.60, lon=121.00),
        stops=[
            Stop(id=1, lat=14.601, lon=121.001, demand=1, tw_start=100, tw_end=200),
            Stop(id=2, lat=14.60, lon=121.13, demand=1, tw_start=0, tw_end=35),
        ],
        fleet=Fleet(count=1, capacity=10),
        speed_kmh=30,
    )
    events = []
    result = run_solver_streaming(
        problem, SolveParams(algorithm="ortools", time_limit_s=3), emit=events.append
    )
    assert result.feasible and result.unassigned_stop_ids == []
    assert events[-1].best_cost == pytest.approx(result.cost, abs=0.01)
    served = {sid for r in events[-1].routes for sid in r}
    assert served == {1, 2}, "streamed incumbent must serve every stop once one such solution exists"
