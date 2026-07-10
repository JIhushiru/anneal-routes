r"""Simulated annealing for the CVRPTW — written from scratch.

The algorithm
-------------
Simulated annealing (Kirkpatrick, Gelatt & Vecchi, 1983) is a stochastic local
search that escapes local minima by sometimes accepting *worse* solutions. Given
the penalized objective f (see evaluate.py) and a proposed neighbor S' of the
current solution S with

    delta = f(S') - f(S),

the move is accepted with the Metropolis probability

    P(accept) = 1              if delta <= 0
    P(accept) = exp(-delta/T)  if delta  > 0

where T is the "temperature". At high T the walk is nearly random (almost every
move accepted — global exploration); as T -> 0 it degenerates into strict descent
over the 2-opt/or-opt/relocate/swap neighborhood (local exploitation). The
Metropolis rule is not arbitrary: at fixed T the induced Markov chain has the
Boltzmann distribution pi_T(S) ∝ exp(-f(S)/T) as its stationary distribution,
which concentrates on global minimizers as T -> 0.

Cooling schedule
----------------
Geometric cooling with a budget-derived ratio:

    T_k = T_0 * alpha^k,   alpha = (T_f / T_0)^(1/K)

where K is the iteration budget. Geometric cooling is the standard practical
choice: the theoretically-guaranteed logarithmic schedule (Hajek, 1988) needs
astronomically many iterations, while a geometric schedule spends comparable
search effort per temperature *decade*, which is where the qualitative behavior
changes. Deriving alpha from (T_0, T_f, K) instead of hard-coding "alpha = 0.999"
makes the trajectory scale-free: every run sweeps the same acceptance range
regardless of budget or instance size.

Endpoint calibration (Ropke & Pisinger, 2006)
---------------------------------------------
Fixed temperatures would be wrong by orders of magnitude across instances (a
Laguna problem has km-scale deltas; with OSRM meters they are 1000x larger), so
the endpoints are tied to the *objective scale*: choose T so that a solution
w% worse than the initial cost f(S_0) is accepted with probability 1/2,

    exp(-(w/100) f(S_0) / T) = 1/2   =>   T = (w/100) f(S_0) / ln 2

with w_start = 5 (melt: 5%-worse solutions pass half the time) and
w_end = 0.01 (freeze: even 0.01%-worse moves are usually refused — the schedule
ends as pure descent over the 2-opt/or-opt/relocate/swap neighborhood).

Why not the older recipe — set T from the mean uphill delta so that a target
fraction of sampled moves is accepted (Johnson et al., 1989)? Because with soft
constraints the sampled-move distribution is bimodal: most deltas are km-scale,
but moves that cross a capacity/time-window boundary jump by LAMBDA_CAP or more.
The mean is dominated by that penalty tail, which (measured on the Metro Manila
scenario) inflates T_0 ~ 25x and — much worse — leaves T_f *above* the typical
km-scale delta, so the "final descent" still accepted ~50% of ordinary uphill
moves and the run never polished its incumbent. Anchoring to a fraction of
f(S_0) is immune to the shape of the move distribution.

Initial solution
----------------
Nearest-neighbor (see nearest_neighbor.py). Annealing from a greedy tour rather
than a random permutation lets the whole budget refine plausible solutions; the
high initial acceptance ratio still provides enough melt to leave the greedy
basin, so the warm start costs nothing in exploration.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Iterator, Optional

from ..schemas import SAParams
from .evaluate import evaluate_route
from .model import RoutingProblem, Solution
from .moves import propose_random_move
from .nearest_neighbor import solve_nearest_neighbor

# Yield a non-improving "tick" event this often, so the temperature curve and
# current-cost trace stream smoothly even between incumbent improvements.
TICK_EVERY = 500
# Recompute the accumulated cost exactly this often to cancel floating-point
# drift from 10^5+ incremental "cost += delta" updates.
RESYNC_EVERY = 10_000


@dataclass(frozen=True)
class SAEvent:
    iteration: int
    temperature: float
    best_cost: float
    current_cost: float
    best_distance_km: float
    improved: bool
    best_solution: Solution
    final: bool = False


@dataclass(frozen=True)
class SAResult:
    best: Solution
    best_cost: float
    best_distance_km: float
    iterations: int
    runtime_ms: float


def _calibrate_temperatures(initial_cost: float, params: SAParams) -> tuple[float, float]:
    """Solve  exp(-(w/100) f(S_0) / T) = 1/2  for the start and end temperatures.

    Anchoring to a fraction of the initial objective keeps the schedule immune to
    penalty-sized outliers in the move-delta distribution (see module docstring).
    ``max(cost, 1.0)`` guards the degenerate near-zero-cost instance.
    """
    scale = max(initial_cost, 1.0)
    t0 = (params.start_accept_worse_pct / 100.0) * scale / math.log(2.0)
    tf = (params.end_accept_worse_pct / 100.0) * scale / math.log(2.0)
    return t0, min(tf, t0)  # a user setting end% > start% must not make alpha > 1


def anneal(
    p: RoutingProblem,
    params: Optional[SAParams] = None,
    time_limit_s: float = 30.0,
    initial: Optional[Solution] = None,
) -> Iterator[SAEvent]:
    """Run SA, yielding an event on every new incumbent and every TICK_EVERY
    iterations. The last event has ``final=True`` and carries the best solution.
    """
    params = params or SAParams()
    rng = random.Random(params.seed)
    started = time.perf_counter()

    current: Solution = [r[:] for r in (initial or solve_nearest_neighbor(p))]
    # Pad with empty routes so relocate can open unused vehicles.
    while len(current) < p.vehicles:
        current.append([])
    evals = [evaluate_route(r, p) for r in current]
    current_cost = sum(e.penalized_cost for e in evals)

    best = [r[:] for r in current]
    best_cost = current_cost
    best_distance = sum(e.distance_km for e in evals)

    t0, tf = _calibrate_temperatures(current_cost, params)
    alpha = (tf / t0) ** (1.0 / params.iterations)
    temperature = t0

    yield SAEvent(0, temperature, best_cost, current_cost, best_distance, True, [r[:] for r in best])

    iteration = 0
    for iteration in range(1, params.iterations + 1):
        # Decay first so events at iteration k always report T_k = T_0 * alpha^k.
        temperature *= alpha

        move = propose_random_move(current, rng)
        if move is not None:
            old_cost = sum(evals[i].penalized_cost for i in move.route_indices)
            new_evals = [evaluate_route(r, p) for r in move.new_routes]
            delta = sum(e.penalized_cost for e in new_evals) - old_cost

            # Metropolis criterion: always accept downhill, accept uphill with
            # probability exp(-delta/T).
            if delta <= 0.0 or rng.random() < math.exp(-delta / temperature):
                move.apply(current)
                for idx, ev in zip(move.route_indices, new_evals):
                    evals[idx] = ev
                current_cost += delta
                if current_cost < best_cost - 1e-9:
                    best = [r[:] for r in current]
                    best_cost = current_cost
                    best_distance = sum(e.distance_km for e in evals)
                    yield SAEvent(
                        iteration, temperature, best_cost, current_cost,
                        best_distance, True, [r[:] for r in best],
                    )

        if iteration % RESYNC_EVERY == 0:
            current_cost = sum(e.penalized_cost for e in evals)
        if iteration % TICK_EVERY == 0:
            yield SAEvent(
                iteration, temperature, best_cost, current_cost,
                best_distance, False, [r[:] for r in best],
            )
            if time.perf_counter() - started > time_limit_s:
                break

    yield SAEvent(
        iteration, temperature, best_cost, current_cost,
        best_distance, False, [r[:] for r in best], final=True,
    )


def solve_sa(
    p: RoutingProblem,
    params: Optional[SAParams] = None,
    time_limit_s: float = 30.0,
) -> SAResult:
    """Drain the annealing generator and return the final incumbent."""
    started = time.perf_counter()
    last: Optional[SAEvent] = None
    for event in anneal(p, params, time_limit_s):
        last = event
    assert last is not None
    return SAResult(
        best=last.best_solution,
        best_cost=last.best_cost,
        best_distance_km=last.best_distance_km,
        iterations=last.iteration,
        runtime_ms=(time.perf_counter() - started) * 1000,
    )
