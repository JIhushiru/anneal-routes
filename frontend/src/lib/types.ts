/** Mirrors of the backend Pydantic schemas (backend/app/schemas.py). */

export type Algorithm = "sa" | "ortools" | "nn";
export type DistanceMode = "haversine" | "osrm";

export interface Stop {
  id: number;
  lat: number;
  lon: number;
  demand: number;
  tw_start: number | null;
  tw_end: number | null;
  service_time: number;
}

export interface Depot {
  lat: number;
  lon: number;
}

export interface Fleet {
  count: number;
  capacity: number;
}

export interface Problem {
  depot: Depot;
  stops: Stop[];
  fleet: Fleet;
  speed_kmh: number;
  distance_mode: DistanceMode;
}

export interface SAParams {
  iterations: number;
  start_accept_worse_pct?: number;
  end_accept_worse_pct?: number;
  seed?: number | null;
}

export interface SolveParams {
  algorithm: Algorithm;
  time_limit_s: number;
  sa: SAParams;
}

export interface TWViolation {
  stop_id: number;
  arrival_min: number;
  tw_end: number;
  lateness_min: number;
}

export interface RouteResult {
  vehicle: number;
  stop_ids: number[];
  arrivals_min: number[];
  load: number;
  capacity_excess: number;
  distance_km: number;
  duration_min: number;
  tw_violations: TWViolation[];
}

export interface SolveResult {
  algorithm: Algorithm;
  total_distance_km: number;
  cost: number;
  runtime_ms: number;
  iterations: number | null;
  feasible: boolean;
  unassigned_stop_ids: number[];
  routes: RouteResult[];
}

export interface ProgressEvent {
  type: "progress";
  iteration: number;
  temperature: number | null;
  best_cost: number;
  current_cost: number;
  best_distance_km: number;
  elapsed_ms: number;
  improved: boolean;
  routes: number[][];
}

export interface DoneEvent {
  type: "done";
  result: SolveResult;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type ServerEvent = ProgressEvent | DoneEvent | ErrorEvent;

export interface ScenarioSummary {
  key: string;
  name: string;
  description: string;
  problem: Problem;
}

export const ALGORITHM_LABELS: Record<Algorithm, string> = {
  sa: "Simulated Annealing",
  ortools: "OR-Tools",
  nn: "Nearest Neighbor",
};
