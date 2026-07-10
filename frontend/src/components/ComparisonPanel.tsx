import { km, ms } from "../lib/format";
import { ALGORITHM_LABELS } from "../lib/types";
import type { RunKey, RunState } from "../state/store";
import { useStore } from "../state/store";

/**
 * Side-by-side verdict after (or during) a comparison run: final cost, distance,
 * runtime, and the gap of the loser relative to the winner's cost.
 */
export function ComparisonPanel() {
  const runs = useStore((s) => s.runs);
  const viewRun = useStore((s) => s.viewRun);
  const patch = useStore((s) => s.patch);

  const costA = runs.A.result?.cost;
  const costB = runs.B.result?.cost;
  const winner: RunKey | null =
    costA !== undefined && costB !== undefined ? (costA <= costB ? "A" : "B") : null;

  return (
    <div className="panel comparison-panel">
      <h2>Head-to-head</h2>
      <div className="compare-cards">
        {(["A", "B"] as const).map((key) => (
          <RunCard
            key={key}
            runKey={key}
            run={runs[key]}
            isWinner={winner === key}
            gapPct={gapPct(runs, key)}
            viewed={viewRun === key}
            onView={() => patch({ viewRun: key })}
          />
        ))}
      </div>
      {winner && (
        <p className="hint">
          Gap % is (cost − best cost) / best cost. Map shows the{" "}
          {viewRun === winner ? "winning" : "highlighted"} run — click a card to switch.
        </p>
      )}
    </div>
  );
}

function gapPct(runs: Record<RunKey, RunState>, key: RunKey): number | null {
  const mine = runs[key].result?.cost;
  const other = runs[key === "A" ? "B" : "A"].result?.cost;
  if (mine === undefined || other === undefined) return null;
  const best = Math.min(mine, other);
  return best > 0 ? ((mine - best) / best) * 100 : 0;
}

function RunCard({
  runKey,
  run,
  isWinner,
  gapPct,
  viewed,
  onView,
}: {
  runKey: RunKey;
  run: RunState;
  isWinner: boolean;
  gapPct: number | null;
  viewed: boolean;
  onView: () => void;
}) {
  return (
    <button
      className={`compare-card ${isWinner ? "winner" : ""} ${viewed ? "viewed" : ""}`}
      onClick={onView}
      disabled={run.status === "idle"}
    >
      <div className="compare-title">
        {run.algorithm ? ALGORITHM_LABELS[run.algorithm] : `Run ${runKey}`}
        {isWinner && <span className="badge ok">winner</span>}
      </div>
      {run.status === "running" && <div className="hint">running…</div>}
      {run.status === "error" && <div className="error-text">{run.error}</div>}
      {run.result && (
        <dl>
          <div>
            <dt>cost</dt>
            <dd>{run.result.cost.toFixed(1)}</dd>
          </div>
          <div>
            <dt>distance</dt>
            <dd>{km(run.result.total_distance_km)}</dd>
          </div>
          <div>
            <dt>gap</dt>
            <dd>{gapPct === null ? "—" : `${gapPct.toFixed(1)}%`}</dd>
          </div>
          <div>
            <dt>runtime</dt>
            <dd>{ms(run.result.runtime_ms)}</dd>
          </div>
          <div>
            <dt>feasible</dt>
            <dd>{run.result.feasible ? "yes" : "NO"}</dd>
          </div>
        </dl>
      )}
    </button>
  );
}
