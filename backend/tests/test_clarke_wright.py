"""Clarke-Wright savings construction: completeness, capacity, and quality."""

from __future__ import annotations

from app.scenarios import SCENARIOS
from app.solver.clarke_wright import solve_clarke_wright
from app.solver.evaluate import solution_distance
from app.solver.model import build_routing_problem
from app.solver.nearest_neighbor import solve_nearest_neighbor


def test_cw_assigns_every_stop_exactly_once():
    for key, sc in SCENARIOS.items():
        p = build_routing_problem(sc["problem"])
        sol = solve_clarke_wright(p)
        assert sorted(n for r in sol for n in r) == list(range(1, p.n + 1)), key
        assert len(sol) == p.vehicles


def test_cw_respects_capacity_when_fleet_suffices():
    for key in ("metro-manila", "laguna"):
        p = build_routing_problem(SCENARIOS[key]["problem"])
        for route in solve_clarke_wright(p):
            assert sum(p.demand[n] for n in route) <= p.capacity + 1e-9, key


def test_cw_beats_nearest_neighbor_on_distance():
    # The whole reason CW is a candidate warm start: savings-based construction
    # should out-build plain greedy on every demo scenario.
    for key, sc in SCENARIOS.items():
        p = build_routing_problem(sc["problem"])
        cw = solution_distance(solve_clarke_wright(p), p)
        nn = solution_distance(solve_nearest_neighbor(p), p)
        assert cw < nn, f"{key}: CW {cw:.1f} km vs NN {nn:.1f} km"
