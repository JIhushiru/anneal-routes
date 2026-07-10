"""Move operators: list mechanics, and 2-opt correctness on known-optimal instances.

The ground-truth argument for the 2-opt tests: for points in convex position the
unique non-crossing Hamiltonian cycle is the hull-order cycle, and it is optimal.
In the (locally Euclidean) plane, any crossing can be removed by a 2-opt exchange
that strictly shortens the tour, so exhaustive 2-opt descent from ANY start must
terminate at the hull tour. Depot-anchored segment reversals cover every cycle
2-opt move: interior reversals handle exchanges not touching the depot, prefix and
suffix reversals handle exchanges of one depot edge, and swapping both depot edges
is a full reversal (cost-neutral on a symmetric matrix).
"""

from __future__ import annotations

import random

import pytest

from app.solver.distance import haversine_matrix
from app.solver.evaluate import evaluate_route
from app.solver.moves import (
    or_opt_relocate,
    propose_random_move,
    two_opt_reverse,
)
from tests.conftest import circle_coords, problem_from_matrix


# ---------------------------------------------------------------- list mechanics


def test_two_opt_reverse_interior_segment():
    assert two_opt_reverse([1, 2, 3, 4, 5], 1, 3) == [1, 4, 3, 2, 5]


def test_two_opt_reverse_prefix_and_suffix():
    assert two_opt_reverse([1, 2, 3, 4], 0, 2) == [3, 2, 1, 4]
    assert two_opt_reverse([1, 2, 3, 4], 2, 3) == [1, 2, 4, 3]


def test_two_opt_reverse_preserves_elements():
    route = [5, 3, 8, 1, 9, 2]
    out = two_opt_reverse(route, 0, 5)
    assert sorted(out) == sorted(route)
    assert out == route[::-1]


def test_two_opt_reverse_rejects_bad_indices():
    with pytest.raises(ValueError):
        two_opt_reverse([1, 2, 3], 2, 2)
    with pytest.raises(ValueError):
        two_opt_reverse([1, 2, 3], 1, 3)


def test_or_opt_relocate_moves_chain_intact():
    # Move chain [2, 3] of route [1, 2, 3, 4, 5] to the end.
    assert or_opt_relocate([1, 2, 3, 4, 5], 1, 2, 3) == [1, 4, 5, 2, 3]
    # Move single element to front.
    assert or_opt_relocate([1, 2, 3], 2, 1, 0) == [3, 1, 2]


def test_or_opt_relocate_rejects_bad_chain():
    with pytest.raises(ValueError):
        or_opt_relocate([1, 2, 3], 2, 2, 0)


# ------------------------------------------------- 2-opt optimality on convex points


def _two_opt_descent(route: list[int], p) -> list[int]:
    """Exhaustive first-improvement 2-opt local search (test helper)."""
    improved = True
    while improved:
        improved = False
        base = evaluate_route(route, p).distance_km
        for i in range(len(route) - 1):
            for j in range(i + 1, len(route)):
                candidate = two_opt_reverse(route, i, j)
                if evaluate_route(candidate, p).distance_km < base - 1e-12:
                    route = candidate
                    improved = True
                    break
            if improved:
                break
    return route


@pytest.mark.parametrize("n_stops", [5, 7, 10])
def test_two_opt_descent_reaches_hull_tour_on_convex_points(n_stops):
    coords = circle_coords(n_stops)
    p = problem_from_matrix(haversine_matrix(coords))
    optimal = evaluate_route(list(range(1, n_stops + 1)), p).distance_km  # hull order

    rng = random.Random(7)
    for _ in range(5):  # several scrambled starts, all must reach the optimum
        route = list(range(1, n_stops + 1))
        rng.shuffle(route)
        final = _two_opt_descent(route, p)
        assert evaluate_route(final, p).distance_km == pytest.approx(optimal, rel=1e-9)


def test_two_opt_uncrosses_square():
    # Unit-ish square, tour visiting opposite corners first (a bowtie).
    # After 2-opt descent the tour must equal the square's perimeter.
    coords = [(14.60, 121.00), (14.60, 121.01), (14.61, 121.01), (14.61, 121.00)]
    p = problem_from_matrix(haversine_matrix(coords))
    crossed = [2, 1, 3]  # depot -> C -> B -> D -> depot crosses itself
    perimeter = evaluate_route([1, 2, 3], p).distance_km
    assert evaluate_route(crossed, p).distance_km > perimeter  # sanity: it IS worse
    final = _two_opt_descent(crossed, p)
    assert evaluate_route(final, p).distance_km == pytest.approx(perimeter, rel=1e-9)


# ------------------------------------------------------------- random proposals


def test_propose_random_move_preserves_multiset_of_stops():
    coords = circle_coords(8)
    p = problem_from_matrix(haversine_matrix(coords), vehicles=3)
    rng = random.Random(123)
    solution = [[1, 2, 3], [4, 5, 6], [7, 8]]
    all_stops = sorted(n for r in solution for n in r)
    for _ in range(500):
        move = propose_random_move(solution, rng)
        assert move is not None
        move.apply(solution)
        assert sorted(n for r in solution for n in r) == all_stops


def test_propose_random_move_handles_degenerate_solutions():
    coords = circle_coords(1)
    p = problem_from_matrix(haversine_matrix(coords))
    rng = random.Random(1)
    # Single stop, single route: only relocate to itself is impossible; the
    # sampler must return None or a valid move, never crash.
    for _ in range(50):
        move = propose_random_move([[1]], rng)
        assert move is None
