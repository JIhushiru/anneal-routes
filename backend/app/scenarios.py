"""Three preloaded demo scenarios.

* ``metro-manila`` — 25 real Metro Manila locations, 4 vans, mixed time windows.
* ``laguna``       — 15 Laguna towns along the Calamba-Santa Cruz corridor, 3 trucks.
* ``random-50``    — 50 seeded-random stops across the NCR bounding box, 6 vans.

Coordinates are hand-picked landmark-adjacent points (malls, town centers,
business districts); demands are unit-free "parcels". Times are minutes from
depot departure — the UI renders t = 0 as 08:00. All three instances are
feasible by construction: demand sums leave >= 15% fleet slack and windows are
wide relative to inter-stop travel times, so hard-constraint solvers (OR-Tools)
and soft-penalty solvers (SA) find the same playing field.

The random scenario is seeded so that benchmarks in the README are reproducible.
"""

from __future__ import annotations

import random

from .schemas import Depot, Fleet, Problem, Stop


def _stop(i: int, lat: float, lon: float, demand: float, tw: tuple[float, float] | None = None,
          service: float = 5.0) -> Stop:
    return Stop(
        id=i, lat=lat, lon=lon, demand=demand,
        tw_start=tw[0] if tw else None, tw_end=tw[1] if tw else None,
        service_time=service,
    )


def _metro_manila() -> Problem:
    # Depot: warehouse district near Port Area, Manila.
    stops = [
        _stop(1, 14.5547, 121.0244, 6, (0, 240)),     # Makati CBD
        _stop(2, 14.5508, 121.0513, 5, (60, 300)),    # BGC, Taguig
        _stop(3, 14.5866, 121.0615, 4, (0, 240)),     # Ortigas Center
        _stop(4, 14.6539, 121.0685, 3),               # UP Diliman, QC
        _stop(5, 14.6202, 121.0532, 4, (120, 360)),   # Cubao, QC
        _stop(6, 14.6507, 121.1029, 3),               # Marikina
        _stop(7, 14.5352, 120.9822, 5, (0, 180)),     # Mall of Asia, Pasay
        _stop(8, 14.4195, 121.0390, 4),               # Alabang, Muntinlupa
        _stop(9, 14.4776, 121.0198, 3),               # BF Homes, Paranaque
        _stop(10, 14.4499, 120.9822, 3),              # Las Pinas
        _stop(11, 14.6570, 120.9840, 4, (60, 300)),   # Caloocan
        _stop(12, 14.7011, 120.9830, 3),              # Valenzuela
        _stop(13, 14.6667, 120.9417, 2),              # Navotas
        _stop(14, 14.6681, 120.9658, 2),              # Malabon
        _stop(15, 14.6019, 121.0355, 3, (120, 420)),  # Greenhills, San Juan
        _stop(16, 14.5794, 121.0359, 4),              # Mandaluyong
        _stop(17, 14.6019, 121.0179, 2),              # Sta. Mesa, Manila
        _stop(18, 14.6003, 120.9749, 3, (0, 240)),    # Binondo, Manila
        _stop(19, 14.5823, 120.9848, 2),              # Ermita, Manila
        _stop(20, 14.6390, 121.0740, 3),              # Katipunan, QC
        _stop(21, 14.7307, 121.0387, 4),              # Novaliches, QC
        _stop(22, 14.7345, 121.0685, 3, (180, 480)),  # Fairview, QC
        _stop(23, 14.5446, 121.0679, 2),              # Pateros
        _stop(24, 14.4880, 121.0522, 3),              # Lower Bicutan, Taguig
        _stop(25, 14.6089, 121.0794, 4, (60, 360)),   # Eastwood, Libis
    ]
    return Problem(
        depot=Depot(lat=14.5995, lon=120.9842),
        stops=stops,
        fleet=Fleet(count=4, capacity=25),
        speed_kmh=25.0,  # Metro Manila traffic
    )


def _laguna() -> Problem:
    stops = [
        _stop(1, 14.3122, 121.1114, 5, (0, 240)),    # Santa Rosa
        _stop(2, 14.3427, 121.0807, 4),              # Binan
        _stop(3, 14.3595, 121.0473, 4),              # San Pedro
        _stop(4, 14.2726, 121.1262, 3, (0, 180)),    # Cabuyao
        _stop(5, 14.1699, 121.2441, 5, (60, 300)),   # Los Banos
        _stop(6, 14.1836, 121.2854, 2),              # Bay
        _stop(7, 14.1497, 121.3152, 3),              # Calauan
        _stop(8, 14.2276, 121.3286, 2),              # Victoria
        _stop(9, 14.2331, 121.3646, 3),              # Pila
        _stop(10, 14.2814, 121.4161, 5, (120, 420)), # Santa Cruz
        _stop(11, 14.2726, 121.4544, 3),             # Pagsanjan
        _stop(12, 14.0683, 121.3251, 6, (120, 420)), # San Pablo
        _stop(13, 14.0637, 121.2461, 3),             # Alaminos
        _stop(14, 14.1361, 121.4165, 2),             # Nagcarlan
        _stop(15, 14.1305, 121.4361, 2),             # Liliw
    ]
    return Problem(
        depot=Depot(lat=14.2117, lon=121.1653),  # Calamba
        stops=stops,
        fleet=Fleet(count=3, capacity=20),
        speed_kmh=40.0,  # provincial highways
    )


def _random_50(seed: int = 42) -> Problem:
    rng = random.Random(seed)
    stops = []
    for i in range(1, 51):
        lat = rng.uniform(14.38, 14.76)
        lon = rng.uniform(120.94, 121.14)
        demand = rng.randint(1, 6)
        tw = None
        if rng.random() < 0.3:
            start = rng.choice([0, 60, 120, 180])
            tw = (float(start), float(start + rng.choice([240, 300, 360])))
        stops.append(_stop(i, round(lat, 5), round(lon, 5), demand, tw))
    return Problem(
        depot=Depot(lat=14.58, lon=121.03),
        stops=stops,
        fleet=Fleet(count=6, capacity=35),
        speed_kmh=30.0,
    )


SCENARIOS: dict[str, dict] = {
    "metro-manila": {
        "name": "Metro Manila — 25 stops",
        "description": "4 vans, 25 landmark stops across NCR, rush-hour speeds, mixed time windows.",
        "problem": _metro_manila(),
    },
    "laguna": {
        "name": "Laguna — 15 stops",
        "description": "3 trucks along the Calamba-Santa Cruz-San Pablo corridor.",
        "problem": _laguna(),
    },
    "random-50": {
        "name": "Random — 50 stops",
        "description": "50 seeded-random stops across the NCR box; the stress test.",
        "problem": _random_50(),
    },
}
