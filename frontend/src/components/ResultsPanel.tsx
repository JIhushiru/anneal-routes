import { routeColorPanel } from "../lib/colors";
import { exportCSV, exportGeoJSON } from "../lib/export";
import { km, minToClock, ms } from "../lib/format";
import { ALGORITHM_LABELS } from "../lib/types";
import { useStore } from "../state/store";

export function ResultsPanel() {
  const run = useStore((s) => s.runs[s.viewRun]);
  const result = run.result;
  // Export against the problem this run actually solved, not the live editor
  // state — the user may have edited/deleted stops since the run finished.
  const problem = run.problem;

  if (!result || !problem) return null;
  const capacity = problem.fleet.capacity;

  return (
    <div className="panel results-panel">
      <h2>
        Result — {ALGORITHM_LABELS[result.algorithm]}{" "}
        {result.feasible ? (
          <span className="badge ok">feasible ✓</span>
        ) : (
          <span className="badge bad">infeasible ✗</span>
        )}
      </h2>
      <div className="stat-row">
        <div className="stat">
          <span className="stat-value">{km(result.total_distance_km)}</span>
          <span className="stat-label">total distance</span>
        </div>
        <div className="stat">
          <span className="stat-value">{result.cost.toFixed(1)}</span>
          <span className="stat-label">penalized cost</span>
        </div>
        <div className="stat">
          <span className="stat-value">{ms(result.runtime_ms)}</span>
          <span className="stat-label">runtime</span>
        </div>
        {result.iterations !== null && (
          <div className="stat">
            <span className="stat-value">{result.iterations.toLocaleString()}</span>
            <span className="stat-label">iterations</span>
          </div>
        )}
      </div>

      {result.unassigned_stop_ids.length > 0 && (
        <p className="error-text">
          Unassigned stops (couldn't fit constraints): {result.unassigned_stop_ids.join(", ")}
        </p>
      )}

      <table className="routes-table">
        <thead>
          <tr>
            <th>Vehicle</th>
            <th>Route</th>
            <th>Load</th>
            <th>Dist</th>
            <th>Time</th>
            <th>TW</th>
          </tr>
        </thead>
        <tbody>
          {result.routes
            .filter((r) => r.stop_ids.length > 0)
            .map((r) => (
              <tr key={r.vehicle}>
                <td>
                  <span className="swatch" style={{ background: routeColorPanel(r.vehicle) }} />
                  #{r.vehicle + 1}
                </td>
                <td className="route-cell" title={r.stop_ids.join(" → ")}>
                  {r.stop_ids.join(" → ")}
                </td>
                <td className={r.capacity_excess > 0 ? "warn" : ""}>
                  {r.load}/{capacity}
                </td>
                <td>{km(r.distance_km)}</td>
                <td>{Math.round(r.duration_min)} min</td>
                <td className={r.tw_violations.length > 0 ? "warn" : ""}>
                  {r.tw_violations.length === 0
                    ? "✓"
                    : r.tw_violations
                        .map((v) => `#${v.stop_id} late ${v.lateness_min.toFixed(0)}m (${minToClock(v.arrival_min)})`)
                        .join("; ")}
                </td>
              </tr>
            ))}
        </tbody>
      </table>

      <div className="row">
        <button onClick={() => exportGeoJSON(problem, result)}>Export GeoJSON</button>
        <button onClick={() => exportCSV(problem, result)}>Export CSV</button>
      </div>
    </div>
  );
}
