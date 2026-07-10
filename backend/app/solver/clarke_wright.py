"""Clarke-Wright parallel savings construction (1964).

Start with one out-and-back route per stop; repeatedly merge the pair of routes
with the largest *saving*

    s(i, j) = d(0, i) + d(0, j) - d(i, j)

— the distance saved by serving j right after i instead of returning to the
depot in between — subject to capacity, merging only at route endpoints
(reversing a route to expose an endpoint is allowed). Typically lands 5-15%
better than nearest-neighbor, which makes it a candidate warm start for the
annealer.

Like NN, this construction is time-window-blind; the penalized objective judges
the result. If more routes than vehicles remain after all feasible merges, the
smallest leftovers are folded in at the cheapest position (overflow allowed and
penalized) so every stop is always assigned.
"""

from __future__ import annotations

from .model import RoutingProblem, Solution
from .nearest_neighbor import _cheapest_insertion


def solve_clarke_wright(p: RoutingProblem) -> Solution:
    dist = p.dist_km
    routes: list[list[int] | None] = [[i] for i in range(1, p.n + 1)]
    loads: list[float] = [p.demand[i] for i in range(1, p.n + 1)]
    route_of: list[int] = list(range(p.n))  # node i -> index into routes (i-1 based)

    savings = sorted(
        ((dist[0][i] + dist[0][j] - dist[i][j], i, j)
         for i in range(1, p.n + 1) for j in range(i + 1, p.n + 1)),
        reverse=True,
    )

    for saving, i, j in savings:
        if saving <= 0:
            break
        a, b = _find(routes, route_of, i), _find(routes, route_of, j)
        if a == b:
            continue
        ra, rb = routes[a], routes[b]
        assert ra is not None and rb is not None
        if loads[a] + loads[b] > p.capacity:
            continue
        # Merge so that i and j become adjacent; reverse a route when the node
        # sits at its head instead of its tail (and vice versa).
        if ra[-1] != i:
            if ra[0] == i:
                ra = ra[::-1]
            else:
                continue  # i is interior — this saving is no longer realizable
        if rb[0] != j:
            if rb[-1] == j:
                rb = rb[::-1]
            else:
                continue
        routes[a] = ra + rb
        loads[a] += loads[b]
        routes[b] = None
        for node in rb:
            route_of[node - 1] = a

    solution: Solution = [r for r in routes if r]
    solution.sort(key=len, reverse=True)

    # Fold the smallest surplus routes into the least-loaded survivors.
    while len(solution) > p.vehicles:
        surplus = solution.pop()
        for node in surplus:
            k = min(range(len(solution)), key=lambda idx: sum(p.demand[n] for n in solution[idx]))
            solution[k] = _cheapest_insertion(solution[k], node, p)

    while len(solution) < p.vehicles:
        solution.append([])
    return solution


def _find(routes: list[list[int] | None], route_of: list[int], node: int) -> int:
    """Resolve a node's current route index (merged-away slots are None)."""
    k = route_of[node - 1]
    if routes[k] is None:
        # The node's slot was merged into another; scan (rare, small n).
        for idx, r in enumerate(routes):
            if r is not None and node in r:
                route_of[node - 1] = idx
                return idx
        raise AssertionError(f"node {node} lost during merges")
    return k
