"""Parallel independent annealing chains — best-of-N at the same wall clock.

Simulated annealing is inherently sequential, but *restarts* are embarrassingly
parallel: run N chains with different seeds in separate processes (separate
GILs), keep the best incumbent. By stochastic dominance,

    min(chain_1, ..., chain_N)  <=  chain_1     (always, per draw)

so the returned quality is weakly better than any single chain *within the same
run* — and run-to-run variance collapses toward the best-of-N distribution,
which is the property that makes benchmark numbers stable. Note the scope: this
does NOT guarantee dominance over a separately-run single-chain solve at the
same wall clock, because spawn overhead shortens each chain's budget and the
budget-driven cooling schedule contracts with it (the repo's own benchmarks show
a single-chain seed occasionally beating the 6-chain best).

Fairness accounting: the wall-clock deadline is fixed BEFORE the processes are
spawned, so process startup (~0.5 s on Windows) eats into the chains' annealing
time rather than extending the budget. A 10-second parallel solve really takes
10 seconds.

Every chain periodically polls a shared stop event, so client cancels propagate
within TICK_EVERY iterations, same as the single-chain path.
"""

from __future__ import annotations

import multiprocessing as mp
import queue as queue_mod
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..schemas import SAParams
from .model import RoutingProblem, Solution
from .sa import SAResult, anneal

# Forward a non-improving tick to the parent this often (in iterations) to keep
# the temperature curve streaming without flooding the IPC queue.
_TICK_FORWARD_EVERY = 2_000
_SEED_STRIDE = 7919  # a prime, so derived seeds never collide across chains


@dataclass(frozen=True)
class ChainEvent:
    """Cross-process progress report, re-emitted by the parent as it sees fit.

    The trajectory fields (iteration, temperature, current_cost) are always
    chain 0's — interleaving N independent walks into one series would render
    the convergence and temperature charts as a sawtooth belonging to no chain.
    Chain 0's schedule is representative (all chains share calibration and
    deadline), while best_cost/best_routes are the true global incumbent.
    """

    chain: int  # chain whose message triggered this event
    iteration: int  # chain 0's iteration count (comparable to a single-chain run)
    temperature: float  # chain 0's temperature
    current_cost: float  # chain 0's current cost
    best_cost: float  # global best across chains
    best_distance_km: float
    improved: bool  # True when the GLOBAL best improved
    best_routes: Solution  # global best routes (node indices)


def _run_chain(
    chain_id: int,
    p: RoutingProblem,
    params: SAParams,
    seed: Optional[int],
    deadline_ts: float,
    out,
    stop_event,
) -> None:
    """Child-process body: run one chain, stream improvements, report the final."""
    time_limit_s = max(0.5, deadline_ts - time.time())
    chain_params = params.model_copy(update={"seed": seed, "chains": 1})
    last_forward = 0
    final = None
    for event in anneal(
        p, chain_params, time_limit_s=time_limit_s, should_stop=stop_event.is_set
    ):
        if event.final:
            final = event
            break
        if event.improved or event.iteration - last_forward >= _TICK_FORWARD_EVERY:
            last_forward = event.iteration
            out.put((
                "progress", chain_id, event.iteration, event.temperature,
                event.best_cost, event.current_cost, event.best_distance_km,
                event.improved, event.best_solution if event.improved else None,
            ))
        if stop_event.is_set():
            # Drain the generator's final polish quickly by breaking out; the
            # incumbent we already hold is what we report.
            final = event
            break
    assert final is not None
    out.put((
        "final", chain_id, final.iteration, final.best_cost,
        final.best_distance_km, final.best_solution,
    ))


def solve_sa_parallel(
    p: RoutingProblem,
    params: SAParams,
    time_limit_s: float = 10.0,
    on_event: Optional[Callable[[ChainEvent], None]] = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> SAResult:
    """Run ``params.chains`` independent chains and return the best incumbent.

    Seeds: chain k gets ``seed + 7919*k`` when a seed is set (reproducible),
    fresh entropy otherwise.
    """
    started = time.perf_counter()
    n_chains = params.chains
    deadline_ts = time.time() + time_limit_s

    ctx = mp.get_context("spawn")
    out: mp.Queue = ctx.Queue()
    stop_event = ctx.Event()
    workers = []
    for k in range(n_chains):
        seed = params.seed + _SEED_STRIDE * k if params.seed is not None else None
        proc = ctx.Process(
            target=_run_chain,
            args=(k, p, params, seed, deadline_ts, out, stop_event),
            daemon=True,
        )
        proc.start()
        workers.append(proc)

    best_cost = float("inf")
    best_distance = 0.0
    best: Optional[Solution] = None
    chain_iterations = [0] * n_chains
    # Chain 0 is the designated trajectory reporter for the charts.
    rep_iteration = 0
    rep_temperature = 0.0
    rep_current = float("inf")
    finals_seen = 0
    workers_died = False

    while finals_seen < n_chains:
        if should_stop() and not stop_event.is_set():
            stop_event.set()
        try:
            msg = out.get(timeout=0.25)
        except queue_mod.Empty:
            if any(w.is_alive() for w in workers):
                continue
            # All workers gone: drain anything still buffered in the pipe, then
            # stop waiting for finals that will never come.
            drained = []
            while True:
                try:
                    drained.append(out.get_nowait())
                except queue_mod.Empty:
                    break
            if not drained:
                workers_died = True
                break
            for msg in drained:
                if msg[0] == "final":
                    _, chain, iteration, cost, dist, routes = msg
                    chain_iterations[chain] = iteration
                    finals_seen += 1
                    if cost < best_cost:
                        best_cost, best_distance, best = cost, dist, routes
            workers_died = finals_seen < n_chains
            break

        kind = msg[0]
        if kind == "progress":
            _, chain, iteration, temperature, cost, current, dist, improved, routes = msg
            chain_iterations[chain] = iteration
            if chain == 0:
                rep_iteration, rep_temperature, rep_current = iteration, temperature, current
            if improved and cost < best_cost and routes is not None:
                best_cost, best_distance, best = cost, dist, routes
                global_improved = True
            else:
                global_improved = False
            if on_event is not None and best is not None:
                on_event(ChainEvent(
                    chain=chain,
                    iteration=rep_iteration,
                    temperature=rep_temperature,
                    current_cost=rep_current if rep_current != float("inf") else cost,
                    best_cost=best_cost,
                    best_distance_km=best_distance,
                    improved=global_improved,
                    best_routes=best,
                ))
        else:  # final
            _, chain, iteration, cost, dist, routes = msg
            chain_iterations[chain] = iteration
            finals_seen += 1
            if cost < best_cost:
                best_cost, best_distance, best = cost, dist, routes

    for w in workers:
        w.join(timeout=5)
        if w.is_alive():
            w.terminate()

    if best is None:
        # Every chain died before reporting (e.g. killed externally). Surface a
        # clear error rather than an assert; callers turn it into an error event.
        raise RuntimeError(
            "all annealing chains exited without reporting a solution"
            + (" (worker processes died)" if workers_died else "")
        )
    return SAResult(
        best=best,
        best_cost=best_cost,
        best_distance_km=best_distance,
        iterations=sum(chain_iterations),
        runtime_ms=(time.perf_counter() - started) * 1000,
    )
