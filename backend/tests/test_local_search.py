"""Descent polish: the never-worsen guarantee, optimality on provable instances,
and stop-multiset preservation."""

from __future__ import annotations

import random

import pytest

from app.scenarios import SCENARIOS
from app.solver.distance import haversine_matrix
from app.solver.evaluate import evaluate_route, solution_cost
from app.solver.local_search import descend
from app.solver.model import build_routing_problem
from app.solver.moves import propose_random_move
from app.solver.nearest_neighbor import solve_nearest_neighbor
from tests.conftest import circle_coords, problem_from_matrix


def _random_solution(p, rng: random.Random):
    """A deliberately bad random solution: stops shuffled into random routes."""
    nodes = list(range(1, p.n + 1))
    rng.shuffle(nodes)
    cuts = sorted(rng.sample(range(len(nodes) + 1), k=p.vehicles - 1)) if p.vehicles > 1 else []
    routes, prev = [], 0
    for c in cuts + [len(nodes)]:
        routes.append(nodes[prev:c])
        prev = c
    return routes


def test_descent_never_worsens():
    rng = random.Random(11)
    for key in ("metro-manila", "laguna", "random-50"):
        p = build_routing_problem(SCENARIOS[key]["problem"])
        for _ in range(3):
            start = _random_solution(p, rng)
            before = solution_cost(start, p)
            after = solution_cost(descend(start, p), p)
            assert after <= before + 1e-9, key


def test_descent_reaches_hull_tour_on_convex_points():
    coords = circle_coords(9)
    p = problem_from_matrix(haversine_matrix(coords), vehicles=1)
    optimal = evaluate_route(list(range(1, 10)), p).distance_km
    rng = random.Random(3)
    for _ in range(4):
        route = list(range(1, 10))
        rng.shuffle(route)
        result = descend([route], p)
        assert evaluate_route(result[0], p).distance_km == pytest.approx(optimal, rel=1e-9)


def test_descent_preserves_stop_multiset():
    p = build_routing_problem(SCENARIOS["metro-manila"]["problem"])
    start = _random_solution(p, random.Random(5))
    result = descend(start, p)
    assert sorted(n for r in result for n in r) == list(range(1, p.n + 1))
    assert len(result) == len(start)


def test_descent_is_deterministic():
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    start = _random_solution(p, random.Random(9))
    assert descend(start, p) == descend(start, p)


def test_descent_output_is_a_local_optimum_for_random_moves():
    # No random move over the same neighborhood should improve a descended solution.
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    sol = descend(solve_nearest_neighbor(p), p)
    base = solution_cost(sol, p)
    rng = random.Random(13)
    for _ in range(3000):
        move = propose_random_move([r[:] for r in sol], rng, p)
        if move is None:
            continue
        candidate = [r[:] for r in sol]
        move.apply(candidate)
        assert solution_cost(candidate, p) >= base - 1e-9
