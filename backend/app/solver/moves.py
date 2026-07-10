"""Neighborhood moves for the simulated-annealing solver.

Each move proposes a small perturbation of the current solution and reports which
routes changed. Cost deltas are computed by re-evaluating only the touched routes
(route-level delta evaluation). With time windows, a change anywhere in a route
shifts every downstream arrival time, so edge-level O(1) deltas — the classic TSP
trick — are not sound here; O(route length) re-evaluation is the honest unit of
incremental work, and at map-editor scale (n <= ~100) it is microseconds.

Moves implemented (names follow the VRP literature):

* ``two_opt``          — intra-route: reverse a segment, removing two crossing edges.
* ``or_opt``           — intra-route: relocate a chain of 1-3 consecutive stops.
* ``relocate``         — inter-route: move one stop to another route (possibly empty).
* ``swap``             — inter-route: exchange one stop between two routes.

Together these connect the search space: relocate/swap redistribute stops across
vehicles (load balancing), while 2-opt and or-opt untangle each vehicle's tour.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .model import Route, Solution


@dataclass(frozen=True)
class Move:
    """A proposed perturbation: replacement contents for one or two routes.

    ``route_indices`` and ``new_routes`` are aligned. Applying the move means
    ``solution[route_indices[k]] = new_routes[k]`` for each k.
    """

    kind: str
    route_indices: tuple[int, ...]
    new_routes: tuple[Route, ...]

    def apply(self, solution: Solution) -> None:
        for idx, new_route in zip(self.route_indices, self.new_routes):
            solution[idx] = new_route


def two_opt_reverse(route: Route, i: int, j: int) -> Route:
    """Return ``route`` with the segment ``route[i..j]`` (inclusive) reversed.

    In edge terms: replaces edges (i-1, i) and (j, j+1) with (i-1, j) and (i, j+1),
    which removes any crossing between those two edges — the classic 2-opt exchange
    (Croes, 1958). Pure function; the caller decides whether to accept.
    """
    if not 0 <= i < j < len(route):
        raise ValueError(f"invalid 2-opt indices i={i}, j={j} for route of length {len(route)}")
    return route[:i] + route[i : j + 1][::-1] + route[j + 1 :]


def or_opt_relocate(route: Route, start: int, length: int, insert_at: int) -> Route:
    """Return ``route`` with the chain ``route[start:start+length]`` removed and
    re-inserted so the chain begins at index ``insert_at`` of the shortened route.

    Or-opt (Or, 1976) preserves the chain's internal order — cheap to evaluate and
    very effective at fixing "one stop stranded on the wrong side of the tour".
    """
    if length < 1 or start < 0 or start + length > len(route):
        raise ValueError(f"invalid or-opt chain start={start} length={length}")
    chain = route[start : start + length]
    rest = route[:start] + route[start + length :]
    if not 0 <= insert_at <= len(rest):
        raise ValueError(f"invalid or-opt insertion index {insert_at}")
    return rest[:insert_at] + chain + rest[insert_at:]


# ---------------------------------------------------------------------------
# Random move proposals. Each returns None when the solution cannot support the
# move (e.g. all stops on one route already), letting the sampler fall through.
# ---------------------------------------------------------------------------


def propose_two_opt(solution: Solution, rng: random.Random) -> Move | None:
    candidates = [k for k, r in enumerate(solution) if len(r) >= 2]
    if not candidates:
        return None
    k = rng.choice(candidates)
    route = solution[k]
    i = rng.randrange(0, len(route) - 1)
    j = rng.randrange(i + 1, len(route))
    return Move("two_opt", (k,), (two_opt_reverse(route, i, j),))


def propose_or_opt(solution: Solution, rng: random.Random) -> Move | None:
    candidates = [k for k, r in enumerate(solution) if len(r) >= 3]
    if not candidates:
        return None
    k = rng.choice(candidates)
    route = solution[k]
    length = rng.randint(1, min(3, len(route) - 1))
    start = rng.randrange(0, len(route) - length + 1)
    rest_len = len(route) - length
    insert_at = rng.randrange(0, rest_len + 1)
    new_route = or_opt_relocate(route, start, length, insert_at)
    if new_route == route:
        return None
    return Move("or_opt", (k,), (new_route,))


def propose_relocate(solution: Solution, rng: random.Random) -> Move | None:
    if len(solution) < 2:
        return None
    sources = [k for k, r in enumerate(solution) if r]
    if not sources:
        return None
    src = rng.choice(sources)
    dst = rng.choice([k for k in range(len(solution)) if k != src])
    src_route = solution[src]
    pos = rng.randrange(len(src_route))
    node = src_route[pos]
    new_src = src_route[:pos] + src_route[pos + 1 :]
    dst_route = solution[dst]
    insert_at = rng.randrange(0, len(dst_route) + 1)
    new_dst = dst_route[:insert_at] + [node] + dst_route[insert_at:]
    return Move("relocate", (src, dst), (new_src, new_dst))


def propose_swap(solution: Solution, rng: random.Random) -> Move | None:
    non_empty = [k for k, r in enumerate(solution) if r]
    if len(non_empty) < 2:
        return None
    a, b = rng.sample(non_empty, 2)
    ra, rb = solution[a], solution[b]
    ia, ib = rng.randrange(len(ra)), rng.randrange(len(rb))
    new_a = ra[:ia] + [rb[ib]] + ra[ia + 1 :]
    new_b = rb[:ib] + [ra[ia]] + rb[ib + 1 :]
    return Move("swap", (a, b), (new_a, new_b))


# Sampling weights: intra-route refinement and inter-route redistribution get
# roughly equal probability mass, which worked best across the demo scenarios
# (see README benchmarks). Exposed as a constant so experiments are one edit away.
MOVE_MENU = (
    (propose_two_opt, 0.30),
    (propose_or_opt, 0.20),
    (propose_relocate, 0.30),
    (propose_swap, 0.20),
)


def propose_random_move(solution: Solution, rng: random.Random) -> Move | None:
    """Sample a move kind by weight, then a uniformly random instance of that kind.

    Falls back through the menu if the sampled kind is inapplicable (e.g. swap
    with a single non-empty route), returning None only when nothing applies.
    """
    r = rng.random() * sum(w for _, w in MOVE_MENU)
    acc = 0.0
    order = []
    for fn, w in MOVE_MENU:
        acc += w
        if r <= acc and not order:
            order.append(fn)
    # Try the sampled kind first, then the rest as fallback.
    for fn, _ in MOVE_MENU:
        if fn not in order:
            order.append(fn)
    for fn in order:
        move = fn(solution, rng)
        if move is not None:
            return move
    return None
