"""Simulated annealing: correctness on known-optimal instances, determinism,
feasibility on the demo scenarios, and event-stream invariants."""

from __future__ import annotations

import pytest

from app.scenarios import SCENARIOS
from app.schemas import SAParams
from app.solver.distance import haversine_matrix
from app.solver.evaluate import evaluate_route, is_feasible, solution_cost
from app.solver.model import build_routing_problem
from app.solver.nearest_neighbor import solve_nearest_neighbor
from app.solver.sa import anneal, solve_sa
from tests.conftest import circle_coords, problem_from_matrix


def test_sa_finds_optimal_tour_on_convex_points():
    # Single vehicle, ample capacity: pure TSP whose optimum is the hull cycle.
    coords = circle_coords(8)
    p = problem_from_matrix(haversine_matrix(coords), vehicles=1)
    optimal = evaluate_route(list(range(1, 9)), p).distance_km

    result = solve_sa(p, SAParams(iterations=30_000, seed=1), time_limit_s=30)
    assert result.best_distance_km == pytest.approx(optimal, rel=1e-9)
    assert is_feasible(result.best, p)


def test_sa_never_worse_than_its_warm_start():
    p = build_routing_problem(SCENARIOS["metro-manila"]["problem"])
    nn_cost = solution_cost(solve_nearest_neighbor(p), p)
    result = solve_sa(p, SAParams(iterations=30_000, seed=2), time_limit_s=30)
    assert result.best_cost <= nn_cost + 1e-9


def test_sa_solution_is_feasible_on_demo_scenarios():
    for key in ("metro-manila", "laguna"):
        p = build_routing_problem(SCENARIOS[key]["problem"])
        result = solve_sa(p, SAParams(iterations=60_000, seed=3), time_limit_s=30)
        assert is_feasible(result.best, p), f"{key}: SA returned an infeasible incumbent"


def test_sa_is_deterministic_for_a_fixed_seed():
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    a = solve_sa(p, SAParams(iterations=15_000, seed=42), time_limit_s=30)
    b = solve_sa(p, SAParams(iterations=15_000, seed=42), time_limit_s=30)
    assert a.best_cost == b.best_cost
    assert a.best == b.best


def test_anneal_event_stream_invariants():
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    events = list(anneal(p, SAParams(iterations=10_000, seed=5), time_limit_s=30))

    assert events[-1].final
    assert all(not e.final for e in events[:-1])
    # Best cost is monotone non-increasing across the stream.
    best_costs = [e.best_cost for e in events]
    assert all(b1 >= b2 - 1e-9 for b1, b2 in zip(best_costs, best_costs[1:]))
    # Temperature is strictly decreasing across iterations (geometric cooling).
    temps = [(e.iteration, e.temperature) for e in events]
    for (i1, t1), (i2, t2) in zip(temps, temps[1:]):
        if i2 > i1:
            assert t2 < t1
    # The reported best cost of the final event matches a fresh evaluation.
    final = events[-1]
    assert final.best_cost == pytest.approx(solution_cost(final.best_solution, p))


def test_sa_respects_vehicle_count():
    p = build_routing_problem(SCENARIOS["metro-manila"]["problem"])
    result = solve_sa(p, SAParams(iterations=20_000, seed=7), time_limit_s=30)
    assert len(result.best) <= p.vehicles
    visited = sorted(n for r in result.best for n in r)
    assert visited == list(range(1, p.n + 1))
