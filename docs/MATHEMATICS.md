# The Mathematics of OptiRoute PH

The project rests on **three mathematical pillars**:

1. **Modeling** — the delivery problem as a constrained combinatorial optimization
   (the CVRPTW), plus the penalized relaxation the search actually walks on.
2. **Geometry** — distances on a sphere (haversine), and the travel-time model
   built on top of them.
3. **Stochastic search** — simulated annealing: the Metropolis rule, why it works
   (Boltzmann stationary distributions), and how the cooling schedule and its
   endpoints are derived rather than guessed.

A fourth section covers the mathematics used to *verify* the first three: known-optimal
test instances, and the benchmarking methodology.

Everything here is implemented in `backend/app/solver/`; each section names the file
that carries it.

---

## 1. Modeling: the CVRPTW

*(implemented across `model.py`, `evaluate.py`; hard-constraint version in `ortools_solver.py`)*

### 1.1 The problem

A depot (node $0$) and stops $\{1,\dots,n\}$, each stop $i$ with demand $q_i \ge 0$,
service time $s_i$, and an optional time window $[e_i, \ell_i]$. A fleet of $m$
identical vehicles with capacity $Q$. A travel cost $d_{ij}$ between every pair of
nodes. Find one tour per vehicle — depot → stops → depot — visiting every stop exactly
once, minimizing total distance.

### 1.2 Formulation

Binary variables $x_{ijk} = 1$ iff vehicle $k$ drives arc $i \to j$; continuous
variables $a_j$ = time service *starts* at stop $j$.

$$
\min \sum_{k=1}^{m}\sum_{i=0}^{n}\sum_{j=0}^{n} d_{ij}\, x_{ijk}
$$

subject to:

| Constraint | Meaning |
|---|---|
| $\sum_k \sum_i x_{ijk} = 1 \quad \forall j \ne 0$ | every stop is entered exactly once |
| $\sum_i x_{ihk} = \sum_j x_{hjk} \quad \forall h, k$ | what enters a node on vehicle $k$ leaves it on vehicle $k$ |
| $\sum_{i \ne 0} q_i \sum_j x_{ijk} \le Q \quad \forall k$ | vehicle load never exceeds capacity |
| $x_{ijk} = 1 \Rightarrow a_j \ge \max(a_i, e_i) + s_i + t_{ij} \quad \forall i,\ \forall j \ne 0$, with $a_0 = 0$ | time propagates along the route ($t_{ij} = d_{ij}/v$) |
| $e_j \le \max(a_j, e_j) \le \ell_j \quad \forall j \ne 0$ with a window | service starts inside the window; arriving early means waiting |

Two modeling details worth spelling out:

**One arrival variable per stop is enough.** Each stop is entered exactly once, so only
one incoming arc ever constrains $a_j$. The depot needs no arrival variable at all:
$a_0 = 0$ is the fixed departure time, and arcs *returning* to the depot are exempt
from time propagation (route duration is not in the objective and the depot has no
window) — hence the $j \ne 0$ quantifier.

**Subtour elimination comes for free.** A classical VRP formulation needs exponentially
many subtour-elimination constraints or a Miller–Tucker–Zemlin (MTZ) ordering variable.
Here the time-propagation constraint *is* the MTZ trick: since $t_{ij} > 0$, the value
of $a$ strictly increases along every arc into a stop. A cycle that avoids the depot
uses only such arcs, so following it once around would prove $a_j > a_j$ — a
contradiction. Any feasible solution therefore consists only of depot-anchored tours.

### 1.3 Complexity

Set $m = 1$, $Q = \infty$, no windows: the CVRPTW collapses to the Traveling Salesman
Problem, which is NP-hard. So the CVRPTW is NP-hard too, and beyond a few dozen stops
exact methods give way to heuristics — which is why the interesting question becomes
*how good is your heuristic*, and why the benchmark section of the README exists.

### 1.4 The penalized relaxation (what the annealer actually minimizes)

Hard constraints are hostile to local search: the feasible region is disconnected under
small moves, so a walk that must stay feasible gets trapped. Instead the metaheuristic
searches over *all* assignments of stops to ordered routes and minimizes

$$
f(S) \;=\; D(S) \;+\; \lambda_{\mathrm{cap}}\, Q^{+}(S) \;+\; \lambda_{\mathrm{tw}}\, W(S)
$$

- $D(S)$ — total distance (km),
- $Q^{+}(S)$ — total capacity excess over all routes (demand units),
- $W(S)$ — total lateness: minutes by which service starts exceed window ends
  (arriving early is free — the vehicle waits, which shifts all downstream arrivals),
- $\lambda_{\mathrm{cap}} = 50$, $\lambda_{\mathrm{tw}} = 2$.

The weights are chosen by a **dominance argument**, not tuning folklore: a whole Metro
Manila tour is 100–200 km, so at $\lambda_{\mathrm{cap}} = 50$ even one unit of
overload outweighs any distance saving available at city scale — a feasible solution
always beats an infeasible one when both are reachable. But the weights are kept
*finite* so the cost surface stays informative: an "almost feasible" solution scores
better than a grossly infeasible one, giving the search a gradient to descend. An
$\infty$ penalty would flatten that signal into a cliff.

Lateness is *accumulated* along the route rather than short-circuiting at the first
violation, for the same reason: $W$ measures *how* infeasible a solution is, not merely
that it is.

---

## 2. Geometry: distances on a sphere

*(implemented in `distance.py`)*

### 2.1 Haversine

Stops are dropped on a map with no road network attached, so the honest distance is the
great-circle geodesic. For two points at latitude/longitude $(\varphi_1, \lambda_1)$,
$(\varphi_2, \lambda_2)$ on a sphere of radius $R$:

$$
\mathrm{hav}(\theta) = \sin^2\!\frac{\Delta\varphi}{2} + \cos\varphi_1 \cos\varphi_2 \sin^2\!\frac{\Delta\lambda}{2},
\qquad
d = 2R \arcsin\!\sqrt{\mathrm{hav}(\theta)}
$$

with $R = 6371.0088$ km (the IUGG mean Earth radius).

**Why this form and not the spherical law of cosines**
($d = R\arccos(\sin\varphi_1\sin\varphi_2 + \cos\varphi_1\cos\varphi_2\cos\Delta\lambda)$)?
Numerical stability. For intra-city separations the law-of-cosines argument is
$1 - \varepsilon$ with $\varepsilon \sim 10^{-10}$; float64 cancellation destroys most
significant digits before $\arccos$ ever sees them. The haversine form computes with
$\sin^2$ of *half-angles* — small numbers represented at full precision. The test suite
pins this down: two points 111 m apart must come out at $111.2 \pm 0.5$ m.

Spherical distance differs from the WGS84 ellipsoid by under 0.5% at Philippine
latitudes — irrelevant when the model error of "distance as the crow flies" is already
far larger. When real roads matter, the OSRM toggle replaces the whole matrix (both
distances and durations) and *nothing else changes*: every solver consumes the same
$(n{+}1)\times(n{+}1)$ matrix abstraction.

### 2.2 The travel-time model

Time is distance at constant speed, $t_{ij} = d_{ij}/v$ (per-scenario $v$: 25 km/h for
Metro Manila traffic, 40 km/h for provincial Laguna), plus fixed service times at each
stop. All times are minutes relative to depot departure ($t = 0$); the UI renders
$t = 0$ as 08:00. This keeps the solver entirely free of wall-clock/timezone concerns.

One subtlety the evaluator gets right (`evaluate.py`): waiting at an early arrival
*shifts every downstream arrival*. Time windows therefore couple the whole suffix of a
route — which is exactly why incremental cost evaluation is subtle (see §3.5).

### 2.3 Matrix properties the search relies on

The haversine matrix is symmetric with zero diagonal and satisfies the triangle
inequality (a metric). The 2-opt "uncrossing" argument in §4.1 leans on the triangle
inequality and on the map being locally flat at city scale. Worth knowing: **real road
matrices (OSRM) can violate symmetry and the triangle inequality** (one-way streets,
U-turn restrictions), which weakens geometric intuition but breaks nothing in the
algorithms — none of the moves *require* a metric; they just search faster on one.

---

## 3. Stochastic search: simulated annealing

*(implemented in `sa.py` and `moves.py`)*

### 3.1 The search space as a graph

A solution is a partition of stops into $\le m$ ordered routes. The neighborhood
operators define edges between solutions:

| move | scope | edge it creates |
|---|---|---|
| 2-opt | intra-route | reverse a contiguous segment |
| or-opt | intra-route | relocate a chain of 1–3 stops within its route |
| relocate | inter-route | move a chain of 1–3 stops to another (possibly empty) route |
| swap | inter-route | exchange one stop between two routes |

Intra-route moves refine each vehicle's tour; inter-route moves redistribute load.
Together they make the solution graph connected — any solution can reach any other
through a finite move sequence, which is a precondition for the convergence theory
below to say anything at all.

### 3.2 The Metropolis rule

From current solution $S$, propose a uniformly random neighbor $S'$ and accept with

$$
P(\text{accept}) =
\begin{cases}
1 & \Delta \le 0\\[2pt]
e^{-\Delta/T} & \Delta > 0
\end{cases}
\qquad \Delta = f(S') - f(S).
$$

This specific rule — not just *any* function that sometimes accepts uphill moves — is
chosen because of what it does to the long-run distribution. For a symmetric proposal
mechanism, the induced Markov chain satisfies **detailed balance** with respect to the
Boltzmann distribution $\pi_T(S) \propto e^{-f(S)/T}$:

$$
\pi_T(S)\, P(S \to S') = \pi_T(S')\, P(S' \to S),
$$

so $\pi_T$ is the chain's stationary distribution at fixed $T$. As $T \to 0$, $\pi_T$
concentrates all its mass on the global minimizers of $f$. Annealing is the practical
gamble that lowering $T$ *slowly enough* keeps the chain near its stationary
distribution all the way down.

(Honesty footnote: our proposal mechanism is only approximately symmetric — each move
kind is its own inverse or has an inverse of the same kind, but the menu's fall-through
when a kind is inapplicable skews proposal probabilities slightly. This is standard
practice in applied SA; the guarantee degrades gracefully rather than breaking.)

**How slowly is "slowly enough"?** Hajek (1988) proved convergence to global optima
requires schedules like $T_k = c/\log(k+1)$ with $c$ at least the depth of the deepest
non-global local minimum — astronomically slow in practice. So practical SA uses
geometric schedules and gives up the guarantee, keeping the mechanism: high $T$
explores basins, low $T$ commits to one.

### 3.3 The cooling schedule

Geometric cooling, parameterized by **budget consumption**:

$$
T(p) = T_0 \left(\frac{T_f}{T_0}\right)^{p},
\qquad
p = \max\!\left(\frac{k}{K},\ \frac{\text{elapsed}}{\text{time limit}}\right) \in [0,1].
$$

When iterations are the binding budget this is exactly the classic
$T_k = T_0\,\alpha^k$ with $\alpha = (T_f/T_0)^{1/K}$. When the wall clock binds, the
schedule contracts so the cooling arc still **completes**.

That last property is not cosmetic. The first version of this code derived $\alpha$
from the iteration cap alone; a 10-second time limit then cut a 5M-iteration schedule
off at ~15% progress, returning a half-melted random walk that was *worse than the
greedy baseline* on the 50-stop scenario. A cooling schedule is a contract about the
whole trajectory — every stop condition has to honor it.

Why geometric at all? It spends comparable search effort per temperature *decade*, and
decades are where behavior changes qualitatively (accept-almost-everything →
accept-selectively → pure descent). Deriving the ratio from $(T_0, T_f, K)$ rather than
hard-coding $\alpha = 0.999$ makes every run sweep the same acceptance range regardless
of budget or instance size.

### 3.4 Endpoint calibration

Fixed temperatures would be wrong across instances by orders of magnitude (km-scale
deltas for Laguna; 1000× larger with OSRM meters). Both endpoints are anchored to the
initial objective $f(S_0)$ (Ropke & Pisinger, 2006): choose $T$ so that a solution
$w\%$ worse than the start is accepted with probability $\tfrac12$:

$$
e^{-(w/100) f(S_0)/T} = \tfrac12
\quad\Longrightarrow\quad
T = \frac{(w/100)\, f(S_0)}{\ln 2},
\qquad
w_{\text{start}} = 5,\quad w_{\text{end}} = 0.01 .
$$

The natural-looking alternative — sample random moves and set $T_0$ from the **mean**
uphill delta so a target fraction is accepted (Johnson et al., 1989) — fails on this
problem, instructively. With soft constraints the move-delta distribution is
**bimodal**: most deltas are km-scale route tweaks, but any move crossing a capacity or
window boundary jumps by $\lambda_{\mathrm{cap}}$ or more. The mean lands in the
penalty tail, inflating $T_0$ ~25× and — much worse — leaving $T_f$ *above* the typical
km-scale delta, so even the "final descent" still accepted ~50% of ordinary uphill
moves and the incumbent never got polished. Measured symptom: some seeds returned the
warm start untouched after 500k iterations. Anchoring to a fraction of $f(S_0)$ is
immune to the *shape* of the delta distribution. This failure is invisible on the
temperature chart and obvious on the best-cost chart — which is much of why the live
visualization exists.

### 3.5 Delta evaluation and numerical hygiene

Classic TSP 2-opt enjoys $O(1)$ deltas: only two edges change. **Time windows destroy
this** — reversing a segment changes arrival times for *every* downstream stop, and
waiting can cascade. So each move re-evaluates only the routes it touches, in full:
$O(\text{route length})$, honest and bug-resistant, microseconds at $n \le 100$.

The running cost is updated incrementally as `cost += delta` ~$10^5$–$10^6$ times per
run; float64 error accumulates, so the accumulated value is resynchronized against a
full evaluation every 10,000 iterations. Cheap insurance against the incumbent drifting
away from the truth.

### 3.6 Warm start

The initial solution is the greedy nearest-neighbor construction (§4.2), not a random
permutation. With $w_{\text{start}} = 5\%$ the early phase still melts enough to escape
the greedy basin, but the budget is spent refining plausible solutions rather than
un-shuffling chaos.

---

## 4. Verification mathematics

### 4.1 Known-optimal instances for 2-opt (the convex-position oracle)

The 2-opt tests need instances where the optimum is *provable*, not just believed:

- **Uncrossing lemma.** If a tour's chords $ab$ and $cd$ cross at point $p$, the
  triangle inequality gives $|ac| + |bd| < (|ap|+|pc|) + (|bp|+|pd|) = |ab| + |cd|$,
  so the 2-opt exchange that removes the crossing strictly shortens the tour.
- **Convex position.** For points on a circle (convex position), the only
  crossing-free Hamiltonian cycle is the hull-order cycle. By the lemma, any 2-opt
  local optimum is crossing-free; therefore exhaustive 2-opt descent from *any*
  scrambled start must terminate at the hull tour — the global optimum.

The tests scramble tours over 5/7/10 points in convex position and assert descent
reaches the hull-perimeter length to $10^{-9}$ relative tolerance, and that SA recovers
the same optimum. (At city scale, lat/lon space is an affine scaling of the plane —
scaling preserves convexity and crossings, so the argument survives haversine.)

### 4.2 The greedy baseline as a control group

Nearest-neighbor construction — each vehicle repeatedly drives to the closest unvisited
stop that fits its remaining capacity — is a *deliberately weak* control: deterministic,
window-blind, sub-millisecond. Its job is to answer "what does the optimization
actually buy?" (31.9–58.0% distance reduction, per the benchmark table) and to provide
the warm start. A known greedy pathology is visible in the data: on the 50-stop
scenario it strands far-flung stops for last and violates their windows.

### 4.3 Benchmark methodology

The claims in the README table are constructed to be *falsifiable*:

- identical instance and distance matrix for all three solvers; one shared evaluator
  prices every solution (OR-Tools' internal objective is never trusted — its routes are
  re-priced by our evaluator);
- equal wall-clock budgets (10 s) for SA and OR-Tools, with SA's iteration cap set high
  enough that time binds;
- SA, being stochastic, reports best/mean/worst over 5 seeds — a point estimate from
  one lucky seed is not a result;
- feasibility of every reported solution is *asserted* by the checker, so "distance"
  comparisons are never quietly comparing a feasible tour against an infeasible one.

Reproduce with `backend/.venv/Scripts/python scripts/benchmark.py --time-limit 10 --sa-runs 5`.

---

## References

- S. Kirkpatrick, C. D. Gelatt, M. P. Vecchi, *Optimization by Simulated Annealing*, Science 220 (1983).
- B. Hajek, *Cooling Schedules for Optimal Annealing*, Mathematics of OR 13(2) (1988).
- D. S. Johnson, C. R. Aragon, L. A. McGeoch, C. Schevon, *Optimization by Simulated Annealing: An Experimental Evaluation, Part I*, Operations Research 37(6) (1989).
- S. Ropke, D. Pisinger, *An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows*, Transportation Science 40(4) (2006).
- G. A. Croes, *A Method for Solving Traveling-Salesman Problems*, Operations Research 6(6) (1958); I. Or, PhD thesis, Northwestern (1976).
- C. E. Miller, A. W. Tucker, R. A. Zemlin, *Integer Programming Formulation of Traveling Salesman Problems*, JACM 7(4) (1960).
