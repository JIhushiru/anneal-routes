"""Greedy nearest-neighbor construction — the control group.

This is deliberately the dumbest reasonable baseline: each vehicle repeatedly
drives to the closest unvisited stop that still fits its remaining capacity,
ignoring time windows entirely. It exists so the README benchmarks can quantify
how much the metaheuristics actually buy over "just be greedy", and it doubles
as the initial solution for simulated annealing (a warm start well inside the
basin of sane solutions beats annealing from a random permutation).
"""

from __future__ import annotations

from .evaluate import evaluate_route
from .model import RoutingProblem, Solution


def solve_nearest_neighbor(p: RoutingProblem) -> Solution:
    """Deterministic greedy construction. Always assigns every stop.

    If demand exceeds total fleet capacity, leftover stops are inserted into the
    least-loaded route at the cheapest position — the result then carries capacity
    excess, which the penalized objective (and the UI) reports honestly rather
    than failing.
    """
    unvisited = set(range(1, p.n + 1))
    routes: Solution = []

    for _ in range(p.vehicles):
        route: list[int] = []
        load = 0.0
        current = 0  # depot
        while unvisited:
            fits = [u for u in unvisited if load + p.demand[u] <= p.capacity]
            if not fits:
                break
            nxt = min(fits, key=lambda u: p.dist_km[current][u])
            route.append(nxt)
            unvisited.remove(nxt)
            load += p.demand[nxt]
            current = nxt
        routes.append(route)

    for node in sorted(unvisited):  # only reachable when fleet capacity is exhausted
        k = min(range(len(routes)), key=lambda i: evaluate_route(routes[i], p).load)
        routes[k] = _cheapest_insertion(routes[k], node, p)

    return routes


def _cheapest_insertion(route: list[int], node: int, p: RoutingProblem) -> list[int]:
    """Insert ``node`` at the position that adds the least distance."""
    best_pos, best_added = 0, float("inf")
    for pos in range(len(route) + 1):
        prev = route[pos - 1] if pos > 0 else 0
        nxt = route[pos] if pos < len(route) else 0
        added = p.dist_km[prev][node] + p.dist_km[node][nxt] - p.dist_km[prev][nxt]
        if added < best_added:
            best_pos, best_added = pos, added
    return route[:best_pos] + [node] + route[best_pos:]
