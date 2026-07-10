import { useEffect, useState } from "react";
import { fetchScenarios } from "../lib/api";
import { compactInt } from "../lib/format";
import type { Algorithm, ScenarioSummary } from "../lib/types";
import { ALGORITHM_LABELS } from "../lib/types";
import { useStore } from "../state/store";

const ALGORITHMS: Algorithm[] = ["sa", "ortools", "nn"];

export function SolverPanel() {
  const s = useStore();
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [scenarioKey, setScenarioKey] = useState("");
  const [scenarioError, setScenarioError] = useState<string | null>(null);

  useEffect(() => {
    fetchScenarios()
      .then((list) => {
        setScenarios(list);
        setScenarioKey(list[0]?.key ?? "");
      })
      .catch((err) => setScenarioError(String(err.message ?? err)));
  }, []);

  const activeRun = s.runs[s.viewRun];
  const lastSample = activeRun.samples[activeRun.samples.length - 1];

  return (
    <div className="panel solver-panel">
      <h2>Scenario</h2>
      <div className="row">
        <select value={scenarioKey} onChange={(e) => setScenarioKey(e.target.value)}>
          {scenarios.map((sc) => (
            <option key={sc.key} value={sc.key}>
              {sc.name}
            </option>
          ))}
        </select>
        <button
          onClick={() => {
            const sc = scenarios.find((x) => x.key === scenarioKey);
            if (sc) s.loadScenario(sc);
          }}
          disabled={!scenarioKey || s.running}
        >
          Load
        </button>
      </div>
      {scenarioError && <p className="error-text">{scenarioError}</p>}
      <div className="row">
        <button
          className={s.editMode === "add-stop" ? "toggle active" : "toggle"}
          onClick={() => s.setEditMode("add-stop")}
          title="Click the map to add numbered stops"
        >
          + Add stops
        </button>
        <button
          className={s.editMode === "set-depot" ? "toggle active" : "toggle"}
          onClick={() => s.setEditMode("set-depot")}
          title="Click the map to place the depot"
        >
          ⌂ Set depot
        </button>
        <button onClick={s.clearAll} disabled={s.running} title="Remove all stops">
          Clear
        </button>
      </div>
      <p className="hint">
        {s.scenarioName ?? `${s.stops.length} stop${s.stops.length === 1 ? "" : "s"}`} · click a
        stop to edit demand / time window, drag to move
      </p>

      <h2>Fleet</h2>
      <div className="row">
        <label>
          Vehicles
          <input
            type="number"
            min={1}
            max={25}
            value={s.fleet.count}
            onChange={(e) =>
              s.patch({ fleet: { ...s.fleet, count: clampInt(e.target.value, 1, 25) } })
            }
          />
        </label>
        <label>
          Capacity
          <input
            type="number"
            min={1}
            value={s.fleet.capacity}
            onChange={(e) =>
              s.patch({ fleet: { ...s.fleet, capacity: Math.max(1, Number(e.target.value)) } })
            }
          />
        </label>
        <label>
          Speed km/h
          <input
            type="number"
            min={5}
            max={120}
            value={s.speedKmh}
            onChange={(e) => s.patch({ speedKmh: clampInt(e.target.value, 5, 120) })}
          />
        </label>
      </div>
      <label className="row checkbox">
        <input
          type="checkbox"
          checked={s.distanceMode === "osrm"}
          onChange={(e) => s.patch({ distanceMode: e.target.checked ? "osrm" : "haversine" })}
        />
        Real road distances (OSRM public API, cached)
      </label>

      <h2>Solver</h2>
      <div className="row">
        <select
          value={s.algorithm}
          onChange={(e) => {
            const algorithm = e.target.value as Algorithm;
            // Keep the comparison partner distinct from the primary.
            const algorithmB =
              algorithm === s.algorithmB
                ? ALGORITHMS.find((a) => a !== algorithm)!
                : s.algorithmB;
            s.patch({ algorithm, algorithmB });
          }}
          disabled={s.running}
        >
          {ALGORITHMS.map((a) => (
            <option key={a} value={a}>
              {ALGORITHM_LABELS[a]}
            </option>
          ))}
        </select>
      </div>
      <label className="row checkbox">
        <input
          type="checkbox"
          checked={s.comparisonMode}
          onChange={(e) => s.patch({ comparisonMode: e.target.checked })}
          disabled={s.running}
        />
        Compare against
        <select
          value={s.algorithmB}
          onChange={(e) => s.patch({ algorithmB: e.target.value as Algorithm })}
          disabled={s.running || !s.comparisonMode}
        >
          {ALGORITHMS.filter((a) => a !== s.algorithm).map((a) => (
            <option key={a} value={a}>
              {ALGORITHM_LABELS[a]}
            </option>
          ))}
        </select>
      </label>
      <div className="row">
        <label>
          Time limit (s)
          <input
            type="number"
            min={1}
            max={120}
            value={s.timeLimitS}
            onChange={(e) => s.patch({ timeLimitS: clampInt(e.target.value, 1, 120) })}
            disabled={s.running}
          />
        </label>
        <label>
          SA iterations
          <input
            type="number"
            min={1000}
            max={5_000_000}
            step={10000}
            value={s.saIterations}
            onChange={(e) =>
              // Backend schema bounds: 1e3 <= iterations <= 5e6.
              s.patch({ saIterations: clampInt(e.target.value, 1000, 5_000_000) })
            }
            disabled={s.running}
          />
        </label>
      </div>

      {s.running ? (
        <button className="run-btn cancel" onClick={s.cancel}>
          ■ Stop
        </button>
      ) : (
        <button className="run-btn" onClick={s.run} disabled={s.stops.length === 0}>
          ▶ Solve
        </button>
      )}

      <div className="status-line">
        {activeRun.status === "running" && lastSample && (
          <>
            <span className="pulse" /> {ALGORITHM_LABELS[activeRun.algorithm ?? "sa"]} · iter{" "}
            {compactInt(lastSample.iteration)} · best {lastSample.best_cost.toFixed(1)} ·{" "}
            {lastSample.elapsed_s.toFixed(1)}s
          </>
        )}
        {activeRun.status === "error" && <span className="error-text">{activeRun.error}</span>}
      </div>
    </div>
  );
}

function clampInt(raw: string, lo: number, hi: number): number {
  const v = Math.round(Number(raw));
  return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo;
}
