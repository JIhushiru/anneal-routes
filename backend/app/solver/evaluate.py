"""Route evaluation: distance, load, time-window simulation, and the penalized objective.

The penalized objective used by the metaheuristics is

    f(S) = D(S) + lambda_cap * Q(S) + lambda_tw * W(S)

where D is total distance (km), Q is total capacity excess (demand units), and W is
total lateness (minutes past a stop's tw_end at arrival). Arriving early is free:
the vehicle waits until the window opens, which is the standard CVRPTW semantics.

Why soft constraints? Simulated annealing needs a connected search space: a chain
of feasible-only solutions between two good solutions often does not exist, so the
walk must be allowed to pass through slightly-infeasible territory and pay for it.
The weights below make one unit of violation clearly worse than any distance saving
available at city scale (a whole Metro Manila tour is ~100-200 km), so the final
incumbent is feasible whenever a feasible solution is reachable.
"""

from __future__ import annotations

from typing import NamedTuple

from .model import Route, RoutingProblem, Solution

# One demand-unit of overload ~ 50 km of driving; one minute late ~ 2 km.
# Large enough to dominate, small enough to keep the cost surface informative
# (a hard "infinity" penalty would flatten the landscape and blind the search).
LAMBDA_CAP = 50.0
LAMBDA_TW = 2.0


class RouteEval(NamedTuple):
    """A NamedTuple (not a dataclass) because the annealer constructs one per
    proposed route, millions per run — tuple construction is several times
    cheaper, and ``penalized_cost`` is precomputed once instead of re-derived
    on every access in the accept/reject arithmetic."""

    distance_km: float
    load: float
    cap_excess: float
    tw_lateness_min: float
    duration_min: float
    arrivals: tuple[float, ...]  # service-start time per stop, aligned with the route
    penalized_cost: float

    @property
    def feasible(self) -> bool:
        return self.cap_excess == 0.0 and self.tw_lateness_min == 0.0


_EMPTY_EVAL = RouteEval(0.0, 0.0, 0.0, 0.0, 0.0, (), 0.0)


def evaluate_route(route: Route, p: RoutingProblem, want_arrivals: bool = True) -> RouteEval:
    """Simulate one vehicle: depot -> stops in order -> depot.

    Time-window semantics: arrival before tw_start incurs a wait (service starts at
    tw_start); *service start* after tw_end counts the excess minutes as lateness.
    Lateness is accumulated but the simulation continues, so W(S) measures total
    violation rather than just flagging the first one — a smoother penalty signal.

    ``want_arrivals=False`` skips building the per-stop arrival tuple; the search
    hot path never reads it (results are re-evaluated fresh at the end), and the
    appends were a measurable share of the whole annealing loop.
    """
    if not route:
        return _EMPTY_EVAL

    # Hot path: hoist per-problem containers out of the loop.
    dist_km = p.dist_km
    time_min = p.time_min
    tw = p.tw
    service = p.service_min
    demand = p.demand

    dist = 0.0
    load = 0.0
    lateness = 0.0
    t = 0.0  # minutes since depot departure
    prev = 0
    arrivals: list[float] | None = [] if want_arrivals else None

    for node in route:
        dist += dist_km[prev][node]
        t += time_min[prev][node]
        window = tw[node]
        if window is not None:
            if t < window[0]:
                t = window[0]  # wait for the window to open
            elif t > window[1]:
                lateness += t - window[1]
        if arrivals is not None:
            arrivals.append(t)
        t += service[node]
        load += demand[node]
        prev = node

    dist += dist_km[prev][0]
    t += time_min[prev][0]

    cap_excess = load - p.capacity
    if cap_excess < 0.0:
        cap_excess = 0.0
    return RouteEval(
        dist,
        load,
        cap_excess,
        lateness,
        t,
        tuple(arrivals) if arrivals is not None else (),
        dist + LAMBDA_CAP * cap_excess + LAMBDA_TW * lateness,
    )


def evaluate_solution(solution: Solution, p: RoutingProblem) -> list[RouteEval]:
    return [evaluate_route(route, p) for route in solution]


def solution_cost(solution: Solution, p: RoutingProblem) -> float:
    return sum(e.penalized_cost for e in evaluate_solution(solution, p))


def solution_distance(solution: Solution, p: RoutingProblem) -> float:
    return sum(e.distance_km for e in evaluate_solution(solution, p))


def is_feasible(solution: Solution, p: RoutingProblem) -> bool:
    """True iff every route respects capacity and all time windows, every stop is
    visited exactly once, and no more than ``p.vehicles`` routes are used."""
    if len(solution) > p.vehicles:
        return False
    visited = [node for route in solution for node in route]
    if sorted(visited) != list(range(1, p.n + 1)):
        return False
    return all(e.feasible for e in evaluate_solution(solution, p))
