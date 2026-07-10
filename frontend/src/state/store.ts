import { create } from "zustand";
import { solveStream, type StreamHandle } from "../lib/api";
import type {
  Algorithm,
  Depot,
  DistanceMode,
  Fleet,
  Problem,
  ScenarioSummary,
  ServerEvent,
  SolveParams,
  SolveResult,
  Stop,
} from "../lib/types";

export interface Sample {
  iteration: number;
  elapsed_s: number;
  best_cost: number;
  current_cost: number;
  temperature: number | null;
}

export interface RunState {
  status: "idle" | "running" | "done" | "error";
  error: string | null;
  algorithm: Algorithm | null;
  /** Snapshot of the problem this run solved — exports and route rendering use
   * this, never the live editor state, which the user may have edited since. */
  problem: Problem | null;
  samples: Sample[];
  liveRoutes: number[][];
  result: SolveResult | null;
}

const idleRun = (): RunState => ({
  status: "idle",
  error: null,
  algorithm: null,
  problem: null,
  samples: [],
  liveRoutes: [],
  result: null,
});

export type RunKey = "A" | "B";
export type EditMode = "add-stop" | "set-depot";

interface AppStore {
  // --- problem being edited on the map
  depot: Depot;
  stops: Stop[];
  fleet: Fleet;
  speedKmh: number;
  distanceMode: DistanceMode;
  nextId: number;
  editMode: EditMode;
  selectedStopId: number | null;
  scenarioName: string | null;

  // --- solver configuration
  algorithm: Algorithm;
  algorithmB: Algorithm;
  comparisonMode: boolean;
  timeLimitS: number;
  saIterations: number;

  // --- run state (single runs live in A; comparison uses A then B)
  runs: Record<RunKey, RunState>;
  running: boolean;
  /** Which run the map is displaying (comparison mode lets the user flip). */
  viewRun: RunKey;

  // --- actions
  addStop(lat: number, lon: number): void;
  updateStop(id: number, patch: Partial<Stop>): void;
  removeStop(id: number): void;
  moveStop(id: number, lat: number, lon: number): void;
  setDepot(lat: number, lon: number): void;
  selectStop(id: number | null): void;
  setEditMode(mode: EditMode): void;
  loadScenario(scenario: ScenarioSummary): void;
  clearAll(): void;
  patch(partial: Partial<AppStore>): void;
  buildProblem(): Problem;
  run(): void;
  cancel(): void;
}

let activeHandle: StreamHandle | null = null;
let cancelled = false;

export const useStore = create<AppStore>((set, get) => {
  function buildParams(algorithm: Algorithm): SolveParams {
    const { timeLimitS, saIterations } = get();
    return {
      algorithm,
      time_limit_s: timeLimitS,
      sa: { iterations: saIterations },
    };
  }

  function startRun(key: RunKey, algorithm: Algorithm, onDone: () => void): void {
    const problem = get().buildProblem();
    set((s) => ({
      runs: { ...s.runs, [key]: { ...idleRun(), status: "running", algorithm, problem } },
      running: true,
      viewRun: key,
    }));
    activeHandle = solveStream(problem, buildParams(algorithm), (event: ServerEvent) => {
      if (event.type === "progress") {
        set((s) => {
          const run = s.runs[key];
          return {
            runs: {
              ...s.runs,
              [key]: {
                ...run,
                samples: [
                  ...run.samples,
                  {
                    iteration: event.iteration,
                    elapsed_s: event.elapsed_ms / 1000,
                    best_cost: event.best_cost,
                    current_cost: event.current_cost,
                    temperature: event.temperature,
                  },
                ],
                liveRoutes: event.routes,
              },
            },
          };
        });
      } else if (event.type === "done") {
        set((s) => ({
          runs: {
            ...s.runs,
            [key]: {
              ...s.runs[key],
              status: "done",
              result: event.result,
              liveRoutes: event.result.routes.map((r) => r.stop_ids),
            },
          },
        }));
        onDone();
      } else {
        set((s) => ({
          runs: { ...s.runs, [key]: { ...s.runs[key], status: "error", error: event.message } },
          running: false,
        }));
      }
    });
  }

  return {
    depot: { lat: 14.5995, lon: 120.9842 },
    stops: [],
    fleet: { count: 3, capacity: 20 },
    speedKmh: 30,
    distanceMode: "haversine",
    nextId: 1,
    editMode: "add-stop",
    selectedStopId: null,
    scenarioName: null,

    algorithm: "sa",
    algorithmB: "ortools",
    comparisonMode: false,
    timeLimitS: 10,
    saIterations: 500_000,

    runs: { A: idleRun(), B: idleRun() },
    running: false,
    viewRun: "A",

    // Problem edits are frozen while a solve runs: a mid-run edit would desync
    // the drawn routes from their stops, and in comparison mode would hand run B
    // a different problem than run A just solved.
    addStop(lat, lon) {
      if (get().running) return;
      set((s) => ({
        stops: [
          ...s.stops,
          { id: s.nextId, lat, lon, demand: 1, tw_start: null, tw_end: null, service_time: 5 },
        ],
        nextId: s.nextId + 1,
        selectedStopId: s.nextId,
        scenarioName: null,
      }));
    },
    updateStop(id, patch) {
      if (get().running) return;
      set((s) => ({ stops: s.stops.map((st) => (st.id === id ? { ...st, ...patch } : st)) }));
    },
    removeStop(id) {
      if (get().running) return;
      set((s) => ({
        stops: s.stops.filter((st) => st.id !== id),
        selectedStopId: s.selectedStopId === id ? null : s.selectedStopId,
      }));
    },
    moveStop(id, lat, lon) {
      get().updateStop(id, { lat, lon });
    },
    setDepot(lat, lon) {
      if (get().running) return;
      set({ depot: { lat, lon } });
    },
    selectStop(id) {
      set({ selectedStopId: id });
    },
    setEditMode(mode) {
      set({ editMode: mode });
    },
    loadScenario(scenario) {
      set({
        depot: scenario.problem.depot,
        stops: scenario.problem.stops,
        fleet: scenario.problem.fleet,
        speedKmh: scenario.problem.speed_kmh,
        distanceMode: scenario.problem.distance_mode,
        nextId: Math.max(0, ...scenario.problem.stops.map((s) => s.id)) + 1,
        scenarioName: scenario.name,
        selectedStopId: null,
        runs: { A: idleRun(), B: idleRun() },
      });
    },
    clearAll() {
      set({
        stops: [],
        nextId: 1,
        selectedStopId: null,
        scenarioName: null,
        runs: { A: idleRun(), B: idleRun() },
      });
    },
    patch(partial) {
      set(partial);
    },
    buildProblem() {
      const { depot, stops, fleet, speedKmh, distanceMode } = get();
      return { depot, stops, fleet, speed_kmh: speedKmh, distance_mode: distanceMode };
    },
    run() {
      const { stops, comparisonMode, algorithm, algorithmB } = get();
      if (stops.length === 0 || get().running) return;
      cancelled = false;
      set({ runs: { A: idleRun(), B: idleRun() } });
      if (comparisonMode) {
        // Sequential, not parallel: both algorithms get the whole CPU, so the
        // runtime column of the comparison is fair.
        startRun("A", algorithm, () => {
          if (cancelled) {
            set({ running: false });
            return;
          }
          startRun("B", algorithmB, () => set({ running: false }));
        });
      } else {
        startRun("A", algorithm, () => set({ running: false }));
      }
    },
    cancel() {
      cancelled = true;
      activeHandle?.cancel(); // terminal: the old stream will never call back again
      activeHandle = null;
      set((s) => ({
        running: false,
        // Keep whatever the cancelled run found so far, shown as finished.
        runs: {
          A: s.runs.A.status === "running" ? { ...s.runs.A, status: "done" } : s.runs.A,
          B: s.runs.B.status === "running" ? { ...s.runs.B, status: "done" } : s.runs.B,
        },
      }));
    },
  };
});
