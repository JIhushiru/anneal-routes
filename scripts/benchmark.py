"""Benchmark the three solvers on the three demo scenarios and print the README table.

Method
------
* Same instance object for every solver (identical haversine matrices).
* SA and OR-Tools each get the SAME wall-clock budget (--time-limit, default 10 s);
  the SA iteration cap is set high enough that the time limit is the binding
  constraint. Nearest-neighbor is a construction heuristic and just runs once.
* SA is stochastic, so it is run --sa-runs times (default 5, seeds 1..N) and the
  table reports best / mean / worst distance plus the mean runtime.
* Costs reported are pure distance (km): every solver's solution is feasible on
  these scenarios, so distance == penalized cost and the comparison is apples to
  apples. Feasibility is asserted, not assumed.

Usage (from repo root):
    backend/.venv/Scripts/python scripts/benchmark.py [--time-limit 10] [--sa-runs 5]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.scenarios import SCENARIOS  # noqa: E402
from app.schemas import SAParams  # noqa: E402
from app.solver.evaluate import is_feasible, solution_distance  # noqa: E402
from app.solver.model import build_routing_problem  # noqa: E402
from app.solver.nearest_neighbor import solve_nearest_neighbor  # noqa: E402
from app.solver.ortools_solver import solve_ortools  # noqa: E402
from app.solver.parallel import solve_sa_parallel  # noqa: E402
from app.solver.sa import solve_sa  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-limit", type=float, default=10.0)
    ap.add_argument("--sa-runs", type=int, default=5)
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument(
        "--only", action="append", choices=list(SCENARIOS), default=None,
        help="run a subset of scenarios (repeatable) — for quick ablation gates",
    )
    ap.add_argument(
        "--chains", type=int, default=0,
        help="also benchmark parallel SA with N chains (0 = skip)",
    )
    args = ap.parse_args()

    selected = {k: v for k, v in SCENARIOS.items() if args.only is None or k in args.only}
    results: dict[str, dict] = {}
    for key, sc in selected.items():
        p = build_routing_problem(sc["problem"])
        print(f"\n=== {sc['name']} (n={p.n}, vehicles={p.vehicles}) ===", flush=True)

        t = time.perf_counter()
        nn = solve_nearest_neighbor(p)
        nn_ms = (time.perf_counter() - t) * 1000
        nn_dist = solution_distance(nn, p)
        nn_feasible = is_feasible(nn, p)
        print(f"  NN        {nn_dist:8.2f} km   {nn_ms:8.1f} ms  feasible={nn_feasible}")

        ot = solve_ortools(p, time_limit_s=args.time_limit)
        assert ot.unassigned == [] and is_feasible(ot.best, p), f"{key}: OR-Tools infeasible"
        print(f"  OR-Tools  {ot.best_distance_km:8.2f} km   {ot.runtime_ms:8.1f} ms")

        sa_dists, sa_times = [], []
        for seed in range(1, args.sa_runs + 1):
            r = solve_sa(
                p,
                SAParams(iterations=5_000_000, seed=seed),
                time_limit_s=args.time_limit,
            )
            assert is_feasible(r.best, p), f"{key}: SA seed {seed} infeasible"
            sa_dists.append(r.best_distance_km)
            sa_times.append(r.runtime_ms)
            print(f"  SA s={seed}    {r.best_distance_km:8.2f} km   {r.runtime_ms:8.1f} ms  "
                  f"({r.iterations:,} iters)")

        results[key] = {
            "name": sc["name"],
            "n": p.n,
            "vehicles": p.vehicles,
            "nn": {"dist_km": round(nn_dist, 2), "ms": round(nn_ms, 1), "feasible": nn_feasible},
            "ortools": {"dist_km": round(ot.best_distance_km, 2), "ms": round(ot.runtime_ms)},
            "sa": {
                "best_km": round(min(sa_dists), 2),
                "mean_km": round(statistics.mean(sa_dists), 2),
                "worst_km": round(max(sa_dists), 2),
                "mean_ms": round(statistics.mean(sa_times)),
                "runs": args.sa_runs,
            },
        }

        if args.chains > 1:
            par_dists, par_times = [], []
            for seed in range(1, args.sa_runs + 1):
                r = solve_sa_parallel(
                    p,
                    SAParams(iterations=5_000_000, seed=seed, chains=args.chains),
                    time_limit_s=args.time_limit,
                )
                assert is_feasible(r.best, p), f"{key}: parallel SA seed {seed} infeasible"
                par_dists.append(r.best_distance_km)
                par_times.append(r.runtime_ms)
                print(f"  SA x{args.chains} s={seed} {r.best_distance_km:8.2f} km   "
                      f"{r.runtime_ms:8.1f} ms  ({r.iterations:,} total iters)")
            results[key]["sa_parallel"] = {
                "chains": args.chains,
                "best_km": round(min(par_dists), 2),
                "mean_km": round(statistics.mean(par_dists), 2),
                "worst_km": round(max(par_dists), 2),
                "mean_ms": round(statistics.mean(par_times)),
                "runs": args.sa_runs,
            }

    print("\n\n--- README markdown ---\n")
    par_col = f" SA ({args.chains} chains) mean |" if args.chains > 1 else ""
    print(f"| Scenario | Greedy (NN) | OR-Tools ({args.time_limit:.0f} s cap) | "
          f"SA best of {args.sa_runs} | SA mean |{par_col} SA vs OR-Tools |")
    print("|---|---|---|---|---|" + ("---|" if args.chains > 1 else "") + "---|")
    any_nn_infeasible = False
    for r in results.values():
        best_sa = min(r["sa"]["best_km"], r.get("sa_parallel", {}).get("best_km", float("inf")))
        gap = (best_sa - r["ortools"]["dist_km"]) / r["ortools"]["dist_km"] * 100
        nn_note = "" if r["nn"]["feasible"] else " †"
        any_nn_infeasible = any_nn_infeasible or not r["nn"]["feasible"]
        par_cell = (
            f" {r['sa_parallel']['mean_km']} km |" if "sa_parallel" in r else ""
        )
        print(
            f"| {r['name']} | {r['nn']['dist_km']} km{nn_note} ({r['nn']['ms']:.0f} ms) "
            f"| {r['ortools']['dist_km']} km ({r['ortools']['ms']/1000:.1f} s) "
            f"| **{r['sa']['best_km']} km** ({r['sa']['mean_ms']/1000:.1f} s) "
            f"| {r['sa']['mean_km']} km "
            f"|{par_cell} {gap:+.1f}% |"
        )
    if any_nn_infeasible:
        print("\n† greedy ignores time windows; this solution violates at least one window.")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
