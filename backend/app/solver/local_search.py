"""Deterministic local-search descent — the post-annealing polish.

Simulated annealing ends stochastically: the final incumbent is near the bottom
of its basin but not provably AT the bottom. This module finishes the job with a
first-improvement descent over the same neighborhood (2-opt, or-opt, relocate,
swap) until a full scan finds no improving move (a local optimum) or a deadline
passes.

The guarantee that makes this worth running unconditionally: descent only ever
applies moves that STRICTLY reduce the penalized objective, so its output is
never worse than its input. Worst case it burns its (small, reserved) time
budget and returns the solution unchanged.

First-improvement (apply the first improving move found, restart the scan) is
chosen over best-improvement (scan everything, apply the single best move):
empirically comparable final quality, much cheaper per pass, and the fixed scan
order keeps the whole descent deterministic — same input, same output.
"""

from __future__ import annotations

import time
from typing import Optional

from .evaluate import RouteEval, evaluate_route
from .model import RoutingProblem, Solution
from .moves import or_opt_relocate, two_opt_reverse, two_opt_star_exchange

# Check the clock every N candidate evaluations, not every one.
_DEADLINE_STRIDE = 256


class _Descent:
    def __init__(self, solution: Solution, p: RoutingProblem, deadline: Optional[float]):
        self.p = p
        self.sol: Solution = [r[:] for r in solution]
        self.evals: list[RouteEval] = [evaluate_route(r, p, False) for r in self.sol]
        self.deadline = deadline
        self._budget_checks = 0
        self.out_of_time = False

    def _expired(self) -> bool:
        if self.deadline is None:
            return False
        self._budget_checks += 1
        if self._budget_checks % _DEADLINE_STRIDE == 0 and time.perf_counter() > self.deadline:
            self.out_of_time = True
        return self.out_of_time

    def _try(self, route_indices: tuple[int, ...], new_routes: tuple[list[int], ...]) -> bool:
        """Apply the candidate iff it strictly improves the penalized cost."""
        old = sum(self.evals[k].penalized_cost for k in route_indices)
        new_evals = [evaluate_route(r, self.p, False) for r in new_routes]
        if sum(e.penalized_cost for e in new_evals) < old - 1e-9:
            for k, route, ev in zip(route_indices, new_routes, new_evals):
                self.sol[k] = route
                self.evals[k] = ev
            return True
        return False

    # Each scan returns True as soon as one improving move was applied.

    def _scan_two_opt(self) -> bool:
        for k, route in enumerate(self.sol):
            for i in range(len(route) - 1):
                for j in range(i + 1, len(route)):
                    if self._expired():
                        return False
                    if self._try((k,), (two_opt_reverse(route, i, j),)):
                        return True
        return False

    def _scan_or_opt(self) -> bool:
        for k, route in enumerate(self.sol):
            for length in (1, 2, 3):
                if len(route) < length + 1:
                    continue
                for start in range(len(route) - length + 1):
                    for insert_at in range(len(route) - length + 1):
                        if self._expired():
                            return False
                        candidate = or_opt_relocate(route, start, length, insert_at)
                        if candidate != route and self._try((k,), (candidate,)):
                            return True
        return False

    def _scan_relocate(self) -> bool:
        # Chains of 1-3, matching the annealer's relocate neighborhood exactly —
        # otherwise the "local optimum" claim would hold for a smaller move set
        # than the one SA searches.
        for src, src_route in enumerate(self.sol):
            for length in (1, 2, 3):
                if len(src_route) < length:
                    continue
                for start in range(len(src_route) - length + 1):
                    chain = src_route[start : start + length]
                    new_src = src_route[:start] + src_route[start + length :]
                    for dst, dst_route in enumerate(self.sol):
                        if dst == src:
                            continue
                        for insert_at in range(len(dst_route) + 1):
                            if self._expired():
                                return False
                            new_dst = dst_route[:insert_at] + chain + dst_route[insert_at:]
                            if self._try((src, dst), (new_src, new_dst)):
                                return True
        return False

    def _scan_two_opt_star(self) -> bool:
        for a in range(len(self.sol)):
            for b in range(len(self.sol)):
                if a == b:
                    continue
                ra, rb = self.sol[a], self.sol[b]
                if not ra:
                    continue
                for i in range(len(ra) + 1):
                    for j in range(len(rb) + 1):
                        if (i == 0 and j == 0) or (i == len(ra) and j == len(rb)):
                            continue
                        if self._expired():
                            return False
                        new_a, new_b = two_opt_star_exchange(ra, rb, i, j)
                        if self._try((a, b), (new_a, new_b)):
                            return True
        return False

    def _scan_swap(self) -> bool:
        for a in range(len(self.sol)):
            for b in range(a + 1, len(self.sol)):
                ra, rb = self.sol[a], self.sol[b]
                for ia in range(len(ra)):
                    for ib in range(len(rb)):
                        if self._expired():
                            return False
                        new_a = ra[:ia] + [rb[ib]] + ra[ia + 1 :]
                        new_b = rb[:ib] + [ra[ia]] + rb[ib + 1 :]
                        if self._try((a, b), (new_a, new_b)):
                            return True
        return False

    def run(self) -> Solution:
        scans = (
            self._scan_two_opt,
            self._scan_or_opt,
            self._scan_relocate,
            self._scan_swap,
            self._scan_two_opt_star,
        )
        improved = True
        while improved and not self.out_of_time:
            improved = any(scan() for scan in scans)
        return self.sol


def descend(
    solution: Solution, p: RoutingProblem, deadline: Optional[float] = None
) -> Solution:
    """First-improvement descent to a local optimum of the penalized objective.

    ``deadline`` is an absolute ``time.perf_counter()`` value; pass None for an
    unbounded descent (it always terminates: each step strictly reduces a cost
    that is bounded below, over a finite solution set).
    Guarantee: cost(result) <= cost(solution), always.
    """
    return _Descent(solution, p, deadline).run()
