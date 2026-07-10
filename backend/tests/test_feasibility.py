"""Feasibility checker and penalized-cost arithmetic on hand-computed instances.

The matrix in most tests uses speed 60 km/h so 1 km == 1 minute and every
expected number can be verified by hand.
"""

from __future__ import annotations

import pytest

from app.solver.evaluate import (
    LAMBDA_CAP,
    LAMBDA_TW,
    evaluate_route,
    is_feasible,
    solution_cost,
)
from tests.conftest import problem_from_matrix

# Depot=0 and stops 1..3 on a line: 0 --10km-- 1 --10km-- 2 --10km-- 3
LINE = [
    [0.0, 10.0, 20.0, 30.0],
    [10.0, 0.0, 10.0, 20.0],
    [20.0, 10.0, 0.0, 10.0],
    [30.0, 20.0, 10.0, 0.0],
]


def test_empty_route_is_all_zeros():
    p = problem_from_matrix(LINE)
    e = evaluate_route([], p)
    assert e.distance_km == 0.0 and e.load == 0.0 and e.duration_min == 0.0
    assert e.feasible


def test_route_distance_and_duration_out_and_back():
    p = problem_from_matrix(LINE)
    e = evaluate_route([1, 2, 3], p)
    # 10 + 10 + 10 out, 30 back = 60 km; at 60 km/h that is 60 minutes.
    assert e.distance_km == pytest.approx(60.0)
    assert e.duration_min == pytest.approx(60.0)
    assert e.arrivals == pytest.approx((10.0, 20.0, 30.0))


def test_service_time_shifts_downstream_arrivals():
    p = problem_from_matrix(LINE, service_min=[0.0, 5.0, 5.0, 5.0])
    e = evaluate_route([1, 2, 3], p)
    assert e.arrivals == pytest.approx((10.0, 25.0, 40.0))
    assert e.duration_min == pytest.approx(75.0)  # 45 depart stop3 + 30 back...


def test_capacity_excess_and_penalty():
    p = problem_from_matrix(LINE, demand=[0.0, 4.0, 4.0, 4.0], capacity=10.0)
    e = evaluate_route([1, 2, 3], p)
    assert e.load == pytest.approx(12.0)
    assert e.cap_excess == pytest.approx(2.0)
    assert not e.feasible
    assert e.penalized_cost == pytest.approx(60.0 + LAMBDA_CAP * 2.0)


def test_wait_when_early_no_penalty():
    # Stop 1 window opens at 30; arrival is 10, so the vehicle waits 20 minutes.
    p = problem_from_matrix(LINE, tw=[None, (30.0, 60.0), None, None])
    e = evaluate_route([1, 2, 3], p)
    assert e.arrivals[0] == pytest.approx(30.0)  # service starts when window opens
    assert e.tw_lateness_min == 0.0
    assert e.feasible
    # Waiting cascades: stop 2 is now reached at 40, stop 3 at 50.
    assert e.arrivals[1:] == pytest.approx((40.0, 50.0))


def test_lateness_measured_and_penalized():
    # Stop 2's window closes at 15 but arrival is 20 -> 5 minutes late.
    p = problem_from_matrix(LINE, tw=[None, None, (0.0, 15.0), None])
    e = evaluate_route([1, 2, 3], p)
    assert e.tw_lateness_min == pytest.approx(5.0)
    assert not e.feasible
    assert e.penalized_cost == pytest.approx(60.0 + LAMBDA_TW * 5.0)


def test_wait_induced_lateness_cascade():
    # Waiting at stop 1 until t=30 makes stop 2 (window closes 35) late by 5.
    p = problem_from_matrix(LINE, tw=[None, (30.0, 60.0), (0.0, 35.0), None])
    e = evaluate_route([1, 2, 3], p)
    assert e.arrivals[1] == pytest.approx(40.0)
    assert e.tw_lateness_min == pytest.approx(5.0)


def test_is_feasible_requires_every_stop_exactly_once():
    p = problem_from_matrix(LINE, vehicles=2)
    assert is_feasible([[1, 2], [3]], p)
    assert not is_feasible([[1, 2], []], p)        # stop 3 missing
    assert not is_feasible([[1, 2, 3], [3]], p)    # stop 3 duplicated
    assert not is_feasible([[1], [2], [3]], p)     # 3 routes > 2 vehicles


def test_solution_cost_is_sum_of_route_costs():
    p = problem_from_matrix(LINE, vehicles=2)
    total = solution_cost([[1], [2, 3]], p)
    e1 = evaluate_route([1], p)
    e2 = evaluate_route([2, 3], p)
    assert total == pytest.approx(e1.penalized_cost + e2.penalized_cost)
    assert total == pytest.approx(20.0 + 60.0)
