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
* ``relocate``         — inter-route: move a chain of 1-3 stops to another route.
* ``swap``             — inter-route: exchange one stop between two routes.
* ``two_opt_star``     — inter-route: cut two routes and exchange their tails
  (Potvin & Rousseau's 2-opt*), the canonical CVRPTW move — it preserves both
  route prefixes, so with time windows the feasible part of each route survives.

Together these connect the search space: relocate/swap/2-opt* redistribute stops
across vehicles (load balancing), while 2-opt and or-opt untangle each tour.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .model import Route, RoutingProblem, Solution

# Probability that an inter-route move targets a k-nearest-neighbor candidate
# instead of a uniformly random position. Biasing toward geographically close
# targets raises the useful-proposal rate enormously at low temperature; the
# 1 - P_NEIGHBOR uniform share keeps long-range moves possible, so the search
# space stays connected and exploration never dies entirely.
P_NEIGHBOR = 0.8


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


def _locate(solution: Solution, node: int, exclude: int) -> tuple[int, int] | None:
    """Find (route index, position) of ``node``, skipping route ``exclude``."""
    for k, route in enumerate(solution):
        if k == exclude:
            continue
        try:
            return k, route.index(node)
        except ValueError:
            continue
    return None


def propose_two_opt(solution: Solution, rng: random.Random, p: RoutingProblem) -> Move | None:
    candidates = [k for k, r in enumerate(solution) if len(r) >= 2]
    if not candidates:
        return None
    k = rng.choice(candidates)
    route = solution[k]
    i = rng.randrange(0, len(route) - 1)
    j = rng.randrange(i + 1, len(route))
    return Move("two_opt", (k,), (two_opt_reverse(route, i, j),))


def propose_or_opt(solution: Solution, rng: random.Random, p: RoutingProblem) -> Move | None:
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


def propose_relocate(solution: Solution, rng: random.Random, p: RoutingProblem) -> Move | None:
    """Move a chain of 1-3 consecutive stops to another route (possibly empty).

    With probability P_NEIGHBOR the insertion point is chosen next to one of the
    chain head's k nearest stops (candidate-list biasing); otherwise — and
    whenever the neighbor happens to sit in the same source route — the
    destination is uniform, which keeps empty routes reachable too.
    """
    if len(solution) < 2:
        return None
    sources = [k for k, r in enumerate(solution) if r]
    if not sources:
        return None
    src = rng.choice(sources)
    src_route = solution[src]
    max_len = min(3, len(src_route))
    length = 1 if max_len == 1 else rng.choice((1, 1, 2, min(3, max_len)))
    start = rng.randrange(0, len(src_route) - length + 1)
    chain = src_route[start : start + length]
    new_src = src_route[:start] + src_route[start + length :]

    if p.neighbors and rng.random() < P_NEIGHBOR:
        nbrs = p.neighbors[chain[0]]
        anchor = nbrs[rng.randrange(len(nbrs))]
        loc = _locate(solution, anchor, exclude=src)
        if loc is not None:
            dst, pos = loc
            insert_at = pos + rng.randint(0, 1)  # just before or just after the anchor
            dst_route = solution[dst]
            new_dst = dst_route[:insert_at] + chain + dst_route[insert_at:]
            return Move("relocate", (src, dst), (new_src, new_dst))

    dst = rng.choice([k for k in range(len(solution)) if k != src])
    dst_route = solution[dst]
    insert_at = rng.randrange(0, len(dst_route) + 1)
    new_dst = dst_route[:insert_at] + chain + dst_route[insert_at:]
    return Move("relocate", (src, dst), (new_src, new_dst))


def two_opt_star_exchange(
    route_a: Route, route_b: Route, i: int, j: int
) -> tuple[Route, Route]:
    """Cut A after position i-1 and B after position j-1; exchange the tails."""
    if not 0 <= i <= len(route_a) or not 0 <= j <= len(route_b):
        raise ValueError(f"invalid 2-opt* cuts i={i}, j={j}")
    return route_a[:i] + route_b[j:], route_b[:j] + route_a[i:]


def propose_two_opt_star(
    solution: Solution, rng: random.Random, p: RoutingProblem
) -> Move | None:
    """Exchange the tails of two routes at random cut points.

    Empty partners are allowed on purpose: a cut against an empty route splits
    an overloaded tour in two, which is how the search opens a fresh vehicle in
    one move instead of relocating stops one by one.
    """
    if len(solution) < 2:
        return None
    non_empty = [k for k, r in enumerate(solution) if r]
    if not non_empty:
        return None
    a = rng.choice(non_empty)
    b = rng.choice([k for k in range(len(solution)) if k != a])
    ra, rb = solution[a], solution[b]
    i = rng.randrange(0, len(ra) + 1)
    j = rng.randrange(0, len(rb) + 1)
    if (i == 0 and j == 0) or (i == len(ra) and j == len(rb)):
        return None  # whole-route swap / no-op: relabelings, never a cost change
    new_a, new_b = two_opt_star_exchange(ra, rb, i, j)
    return Move("two_opt_star", (a, b), (new_a, new_b))


def propose_swap(solution: Solution, rng: random.Random, p: RoutingProblem) -> Move | None:
    """Exchange one stop between two routes, biased toward swapping with one of
    the picked stop's k nearest neighbors (same rationale as relocate)."""
    non_empty = [k for k, r in enumerate(solution) if r]
    if len(non_empty) < 2:
        return None
    a = rng.choice(non_empty)
    ra = solution[a]
    ia = rng.randrange(len(ra))

    if p.neighbors and rng.random() < P_NEIGHBOR:
        nbrs = p.neighbors[ra[ia]]
        anchor = nbrs[rng.randrange(len(nbrs))]
        loc = _locate(solution, anchor, exclude=a)
        if loc is not None:
            b, ib = loc
            rb = solution[b]
            new_a = ra[:ia] + [rb[ib]] + ra[ia + 1 :]
            new_b = rb[:ib] + [ra[ia]] + rb[ib + 1 :]
            return Move("swap", (a, b), (new_a, new_b))

    others = [k for k in non_empty if k != a]
    if not others:
        return None
    b = rng.choice(others)
    rb = solution[b]
    ib = rng.randrange(len(rb))
    new_a = ra[:ia] + [rb[ib]] + ra[ia + 1 :]
    new_b = rb[:ib] + [ra[ia]] + rb[ib + 1 :]
    return Move("swap", (a, b), (new_a, new_b))


# Sampling weights: intra-route refinement and inter-route redistribution get
# roughly equal probability mass, which worked best across the demo scenarios
# (see README benchmarks). Exposed as a constant so experiments are one edit away.
MOVE_MENU = (
    (propose_two_opt, 0.25),
    (propose_or_opt, 0.15),
    (propose_relocate, 0.25),
    (propose_swap, 0.15),
    (propose_two_opt_star, 0.20),
)


# Precomputed dispatch tables: the sampler runs a million times per solve, so
# the cumulative thresholds and function order are baked once at import.
_MENU_FNS = tuple(fn for fn, _ in MOVE_MENU)
_MENU_TOTAL = sum(w for _, w in MOVE_MENU)
_MENU_CUM = tuple(
    sum(w for _, w in MOVE_MENU[: i + 1]) for i in range(len(MOVE_MENU))
)


def propose_random_move(
    solution: Solution, rng: random.Random, p: RoutingProblem
) -> Move | None:
    """Sample a move kind by weight, then a random instance of that kind.

    Falls back through the menu if the sampled kind is inapplicable (e.g. swap
    with a single non-empty route), returning None only when nothing applies.
    """
    r = rng.random() * _MENU_TOTAL
    first = 0
    for i, threshold in enumerate(_MENU_CUM):
        if r <= threshold:
            first = i
            break
    move = _MENU_FNS[first](solution, rng, p)
    if move is not None:
        return move
    for i, fn in enumerate(_MENU_FNS):
        if i == first:
            continue
        move = fn(solution, rng, p)
        if move is not None:
            return move
    return None
