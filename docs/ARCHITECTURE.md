# Architecture & Tech

How OptiRoute PH is put together: the stack, the module boundaries, and the four
design decisions that shape everything else. The math behind the solvers lives in
[MATHEMATICS.md](MATHEMATICS.md); this doc is about the system.

## Stack at a glance

| Layer | Technology | Why |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite | strict types across the wire format; instant dev loop |
| Map | MapLibre GL + OpenFreeMap tiles | free vector tiles, no API key, GeoJSON sources redraw at streaming rate |
| Charts | Recharts | declarative, fine for ~30 fps series with animations off |
| State | zustand | one store, no boilerplate; run orchestration lives beside the data it mutates |
| Backend | FastAPI + Python 3.11+ | Pydantic schemas double as the API contract; native WebSocket support |
| Solvers | pure Python (SA) + Google OR-Tools (baseline) | the SA is the from-scratch showpiece; OR-Tools keeps it honest |
| Transport | REST + one WebSocket | request/response for data, one socket per solve for streaming |
| Deploy | docker-compose (backend + nginx frontend), or `python run.py` locally | one command either way |

## Repository layout

```
run.py                    # local launcher: bootstraps, starts both services, Ctrl+C stops both
docker-compose.yml        # containerized path: backend + nginx-served frontend
scripts/benchmark.py      # produces the README numbers (never hand-edit those)
benchmarks/results.json   # raw output of the last benchmark run
docs/                     # this file, MATHEMATICS.md, screenshots
backend/
  app/
    schemas.py            # Pydantic wire format — THE contract, mirrored by the frontend
    main.py               # FastAPI app + /ws/solve socket handler
    service.py            # orchestration: prepare instance, run solver, assemble result
    scenarios.py          # the three demo instances (Metro Manila / Laguna / random-50)
    osrm.py               # road-distance matrices via OSRM, disk-cached
    solver/               # no FastAPI imports below this line — pure algorithms
      model.py            # RoutingProblem: index-based instance every solver consumes
      distance.py         # haversine matrix
      evaluate.py         # feasibility + penalized cost — single source of truth
      moves.py            # 2-opt, or-opt, relocate, swap, 2-opt* (+ candidate-list bias)
      nearest_neighbor.py # greedy construction
      clarke_wright.py    # savings construction (warm start)
      sa.py               # simulated annealing (generator-based)
      local_search.py     # deterministic descent (final polish)
      parallel.py         # best-of-N chains via multiprocessing
      ortools_solver.py   # OR-Tools CVRPTW wrapper
  tests/                  # 62 tests: math oracles, invariants, API round-trips
frontend/
  src/
    lib/types.ts          # hand-mirrored schemas.py (kept in lockstep)
    lib/api.ts            # fetch + WebSocket client (solveStream)
    lib/colors.ts         # validated categorical palette, per-surface steppings
    lib/export.ts         # GeoJSON / CSV download
    state/store.ts        # zustand store + run orchestration (single & comparison)
    components/           # MapView, SolverPanel, charts, ResultsPanel, ComparisonPanel
```

## The four load-bearing decisions

### 1. One evaluator prices everything

`solver/evaluate.py` is the only code that knows what a solution costs. SA searches
with it, the descent polish uses it, results are assembled from it — and OR-Tools'
routes are **re-priced by it** rather than trusting OR-Tools' internal objective.
Consequence: every number the app shows (streamed costs, final results, benchmark
table) is comparable with every other, and a bug in cost logic can only live in one
file. The internal `RoutingProblem` (node 0 = depot, matrices precomputed) is likewise
the single instance format all solvers consume, so swapping haversine for OSRM road
distances is a matrix substitution and nothing else changes.

### 2. Solvers are synchronous generators; the API adapts them

The annealer is a plain Python generator that yields progress events — it knows
nothing about WebSockets, threads, or JSON. The layering:

```
anneal() generator            (solver/sa.py — pure, testable, seedable)
  └─ run_solver_streaming()   (service.py — sync, emits ProgressEvent via callback)
       └─ worker thread       (main.py — CPU work off the event loop)
            └─ asyncio.Queue  (call_soon_threadsafe hands events to the loop)
                 └─ /ws/solve (coalesces bursts to ~30 fps, sends JSON frames)
```

Early in a solve SA can improve thousands of times per second; the socket handler
drains the queue and keeps only the newest progress frame per ~30 ms window. Every
frame carries the full incumbent routes, so dropping intermediate frames loses
nothing — the map can redraw from any single frame. Terminal `done`/`error` events
are never coalesced away. Cancellation is a `threading.Event` polled between solver
events **and inside the descent polish**; OR-Tools runs are interrupted at their next
solution callback.

### 3. The wire format is the contract

`schemas.py` (Pydantic) defines `Problem`, `SolveParams`, `ProgressEvent`,
`SolveResult`; `frontend/src/lib/types.ts` mirrors them field-for-field. The WebSocket
protocol is four message types:

```
client → server   {type: "solve", problem, params}   |   {type: "cancel"}
server → client   {type: "progress", iteration, temperature, best_cost,
                   current_cost, best_distance_km, elapsed_ms, improved, routes}
                  {type: "done", result}   |   {type: "error", message}
```

Rules that keep it robust: unparseable client frames are ignored (never treated as a
cancel); the client's `cancel()` waits for the server's close handshake instead of
slamming the socket; a cancelled stream never delivers another event, so a stale run
can't corrupt a newer run's state. Times are minutes from depot departure (t = 0);
the UI renders t = 0 as 08:00 — the solver never sees wall-clock time.

### 4. Parallel chains are processes, and chain 0 narrates

`chains > 1` runs N independent annealers via `multiprocessing` (spawn) — separate
GILs, separate RNGs (seed + 7919·k). The parent tracks the global best incumbent for
the map, but the convergence/temperature charts follow **chain 0 only**: interleaving
N independent random walks into one series would draw a sawtooth belonging to no
chain. The wall-clock deadline is fixed *before* spawning, so process startup eats
into the chains' budget rather than extending it — a 10-second solve takes 10 seconds.
Cancels propagate through a shared `multiprocessing.Event`; a dead worker pool is
drained for buffered results and surfaces as a clean error, not a hang.

## Frontend structure

`store.ts` owns everything: the editable problem (stops/depot/fleet), solver config,
and two run slots (`A`/`B`) so comparison mode is just "run A, then run B on the same
problem, sequentially — both get the whole CPU". Each run snapshots the problem it
solved, so exports and route rendering survive later edits; edits are frozen while a
solve runs. `MapView` subscribes to the viewed run's live routes and rewrites two
GeoJSON sources (stops, routes) per frame; route colors come from a
colorblind-validated palette with per-surface steppings (light map lines, dark panel
swatches — same hue identity per vehicle).

## Configuration & deployment

- **Local:** `python run.py` — creates the venv / node_modules on first run, starts
  uvicorn + vite, auto-falls-back if a default port is taken (8000 is popular),
  proxies `/api` and `/ws` through vite (`BACKEND_URL` env). Ctrl+C tears down both.
- **Docker:** `docker compose up --build` — backend container (python:3.11-slim) and
  an nginx container serving the built frontend and proxying `/api` + `/ws` (with
  websocket upgrade headers) to the backend service. The OSRM response cache lives in
  a named volume.
- **OSRM mode:** optional per-solve toggle; matrices come from the public
  router.project-osrm.org `/table` endpoint, cached on disk by coordinate hash
  (≤100 locations, matrices with unroutable pairs are not cached).

## Testing & benchmarking

Tests are organized around *provable* oracles rather than snapshots: convex-position
instances whose optimal tour is a theorem (2-opt and SA must find it), hand-computed
feasibility arithmetic (1 km = 1 min), known geodesics for haversine, invariant fuzzing
(every move preserves the stop multiset), determinism per seed, dominance properties
of the polish and chains, and API/WebSocket round-trips.

`scripts/benchmark.py` produces the README table (5 seeds, equal wall-clock budgets,
feasibility asserted). House rule: any solver change must pass a 5-seed gate on the
50-stop scenario before it lands, and README numbers must match
`benchmarks/results.json` exactly.
