"""Parallel best-of-N chains: dominance over the contained single chain,
feasibility, and event-stream sanity."""

from __future__ import annotations

import pytest

from app.scenarios import SCENARIOS
from app.schemas import SAParams
from app.solver.evaluate import is_feasible
from app.solver.model import build_routing_problem
from app.solver.parallel import solve_sa_parallel
from app.solver.sa import solve_sa


def test_parallel_beats_or_ties_the_contained_single_chain():
    # Chain 0 runs seed 42 with the same iteration budget as the single-chain
    # run; both are iteration-bound (generous time limit), hence deterministic —
    # so best-of-2 must be <= the single chain's result.
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    single = solve_sa(p, SAParams(iterations=15_000, seed=42), time_limit_s=60)
    parallel = solve_sa_parallel(
        p, SAParams(iterations=15_000, seed=42, chains=2), time_limit_s=60
    )
    assert parallel.best_cost <= single.best_cost + 1e-9


def test_parallel_solution_is_feasible_and_complete():
    p = build_routing_problem(SCENARIOS["metro-manila"]["problem"])
    result = solve_sa_parallel(
        p, SAParams(iterations=20_000, seed=7, chains=3), time_limit_s=60
    )
    assert is_feasible(result.best, p)
    assert sorted(n for r in result.best for n in r) == list(range(1, p.n + 1))
    # Total iterations should reflect all chains' work.
    assert result.iterations > 20_000 * 2


def test_parallel_streams_monotone_global_best():
    p = build_routing_problem(SCENARIOS["laguna"]["problem"])
    events = []
    solve_sa_parallel(
        p, SAParams(iterations=15_000, seed=1, chains=2), time_limit_s=60,
        on_event=events.append,
    )
    assert events, "expected progress events from the chains"
    best_costs = [e.best_cost for e in events]
    assert all(b1 >= b2 - 1e-9 for b1, b2 in zip(best_costs, best_costs[1:]))
    assert all(e.best_routes for e in events)


def test_parallel_cancel_stops_early():
    p = build_routing_problem(SCENARIOS["metro-manila"]["problem"])
    seen = {"n": 0}

    def should_stop() -> bool:
        return seen["n"] >= 3

    def on_event(ev) -> None:
        seen["n"] += 1

    result = solve_sa_parallel(
        p,
        SAParams(iterations=5_000_000, seed=2, chains=2),
        time_limit_s=60,
        on_event=on_event,
        should_stop=should_stop,
    )
    # 5M iterations at ~80k/s would take ~60s per chain; a cancel after 3 events
    # must come back far sooner, with a usable incumbent.
    assert result.runtime_ms < 30_000
    assert result.best
