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

from dataclasses import dataclass

from .model import Route, RoutingProblem, Solution

# One demand-unit of overload ~ 50 km of driving; one minute late ~ 2 km.
# Large enough to dominate, small enough to keep the cost surface informative
# (a hard "infinity" penalty would flatten the landscape and blind the search).
LAMBDA_CAP = 50.0
LAMBDA_TW = 2.0


@dataclass(frozen=True)
class RouteEval:
    distance_km: float
    load: float
    cap_excess: float
    tw_lateness_min: float
    duration_min: float
    arrivals: tuple[float, ...]  # service-start time per stop, aligned with the route

    @property
    def penalized_cost(self) -> float:
        return self.distance_km + LAMBDA_CAP * self.cap_excess + LAMBDA_TW * self.tw_lateness_min

    @property
    def feasible(self) -> bool:
        return self.cap_excess == 0.0 and self.tw_lateness_min == 0.0


def evaluate_route(route: Route, p: RoutingProblem) -> RouteEval:
    """Simulate one vehicle: depot -> stops in order -> depot.

    Time-window semantics: arrival before tw_start incurs a wait (service starts at
    tw_start); *service start* after tw_end counts the excess minutes as lateness.
    Lateness is accumulated but the simulation continues, so W(S) measures total
    violation rather than just flagging the first one — a smoother penalty signal.
    """
    if not route:
        return RouteEval(0.0, 0.0, 0.0, 0.0, 0.0, ())

    dist = 0.0
    load = 0.0
    lateness = 0.0
    t = 0.0  # minutes since depot departure
    prev = 0
    arrivals: list[float] = []

    for node in route:
        dist += p.dist_km[prev][node]
        t += p.time_min[prev][node]
        window = p.tw[node]
        if window is not None:
            if t < window[0]:
                t = window[0]  # wait for the window to open
            elif t > window[1]:
                lateness += t - window[1]
        arrivals.append(t)
        t += p.service_min[node]
        load += p.demand[node]
        prev = node

    dist += p.dist_km[prev][0]
    t += p.time_min[prev][0]

    return RouteEval(
        distance_km=dist,
        load=load,
        cap_excess=max(0.0, load - p.capacity),
        tw_lateness_min=lateness,
        duration_min=t,
        arrivals=tuple(arrivals),
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
