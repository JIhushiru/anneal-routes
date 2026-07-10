"""Pydantic schemas shared by the REST API, the WebSocket protocol, and the solvers.

Conventions
-----------
* Coordinates are WGS84 ``(lat, lon)``.
* All times are **minutes relative to the depot departure** (t = 0). The UI is free
  to render t = 0 as 08:00 or anything else; the solver never sees wall-clock time.
* Demands and capacities are unit-free (parcels, kg, crates — user's choice).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class Algorithm(str, Enum):
    SIMULATED_ANNEALING = "sa"
    OR_TOOLS = "ortools"
    NEAREST_NEIGHBOR = "nn"


class DistanceMode(str, Enum):
    HAVERSINE = "haversine"
    OSRM = "osrm"


class Stop(BaseModel):
    """A delivery stop placed on the map."""

    id: int = Field(ge=1, description="Stable client-side id (1-based, unique per problem)")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    demand: float = Field(default=1.0, ge=0)
    tw_start: Optional[float] = Field(
        default=None, ge=0, description="Earliest service start, minutes from depot departure"
    )
    tw_end: Optional[float] = Field(
        default=None, ge=0, description="Latest service start, minutes from depot departure"
    )
    service_time: float = Field(default=5.0, ge=0, description="On-site service duration, minutes")

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "Stop":
        if self.tw_start is not None and self.tw_end is not None and self.tw_end < self.tw_start:
            raise ValueError(f"stop {self.id}: tw_end < tw_start")
        return self


class Depot(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Fleet(BaseModel):
    count: int = Field(ge=1, le=25)
    capacity: float = Field(gt=0)


class Problem(BaseModel):
    """A complete CVRPTW instance as edited on the map."""

    depot: Depot
    stops: list[Stop] = Field(min_length=1)
    fleet: Fleet
    speed_kmh: float = Field(default=30.0, gt=0, description="Assumed travel speed for time windows")
    distance_mode: DistanceMode = DistanceMode.HAVERSINE

    @model_validator(mode="after")
    def _unique_stop_ids(self) -> "Problem":
        ids = [s.id for s in self.stops]
        if len(ids) != len(set(ids)):
            raise ValueError("stop ids must be unique")
        return self


class SAParams(BaseModel):
    """Tunables for the simulated-annealing solver. Defaults are justified in sa.py.

    Temperatures are parameterized as "accept a solution X% worse than the start
    with probability 1/2" (Ropke & Pisinger, 2006) — scale-free and robust to
    penalty-sized cost jumps in the move distribution.
    """

    iterations: int = Field(default=500_000, ge=1_000, le=5_000_000)
    start_accept_worse_pct: float = Field(
        default=5.0, gt=0, le=100,
        description="T0: a move this % worse than the initial cost is accepted w.p. 0.5",
    )
    end_accept_worse_pct: float = Field(
        default=0.01, gt=0, le=100,
        description="Tf: same rule at the final iteration (effectively pure descent)",
    )
    chains: int = Field(
        default=1, ge=1, le=16,
        description="Independent SA runs in parallel processes; the best incumbent wins "
        "(best-of-N stochastic dominance at the same wall clock)",
    )
    seed: Optional[int] = Field(default=None, description="RNG seed for reproducible runs")


class SolveParams(BaseModel):
    algorithm: Algorithm
    time_limit_s: float = Field(default=10.0, gt=0, le=120)
    sa: SAParams = Field(default_factory=SAParams)


class TWViolation(BaseModel):
    stop_id: int
    arrival_min: float
    tw_end: float
    lateness_min: float


class RouteResult(BaseModel):
    vehicle: int
    stop_ids: list[int] = Field(description="Visit order, depot excluded")
    arrivals_min: list[float] = Field(description="Service-start time per stop, aligned with stop_ids")
    load: float
    capacity_excess: float
    distance_km: float
    duration_min: float
    tw_violations: list[TWViolation]


class SolveResult(BaseModel):
    algorithm: Algorithm
    total_distance_km: float
    cost: float = Field(description="Penalized objective: distance + capacity/time-window penalties")
    runtime_ms: float
    iterations: Optional[int] = None
    feasible: bool
    unassigned_stop_ids: list[int] = Field(default_factory=list)
    routes: list[RouteResult]


# --------------------------------------------------------------------------------------
# WebSocket protocol
#
# Client -> server:   {"type": "solve", "problem": {...}, "params": {...}}
#                     {"type": "cancel"}
# Server -> client:   {"type": "progress", ...}   on every improvement / periodic tick
#                     {"type": "done", "result": {...}}
#                     {"type": "error", "message": "..."}
# --------------------------------------------------------------------------------------


class SolveRequest(BaseModel):
    type: Literal["solve"] = "solve"
    problem: Problem
    params: SolveParams


class ProgressEvent(BaseModel):
    type: Literal["progress"] = "progress"
    iteration: int
    temperature: Optional[float] = Field(default=None, description="SA only; null for other solvers")
    best_cost: float
    current_cost: float
    best_distance_km: float
    elapsed_ms: float
    improved: bool = Field(description="True when this event is a new incumbent, not a periodic tick")
    routes: list[list[int]] = Field(description="Stop ids per vehicle for the incumbent solution")


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    result: SolveResult


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
