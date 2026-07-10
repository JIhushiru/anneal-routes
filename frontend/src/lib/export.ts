/** Solution export: GeoJSON (depot + stops + route lines) and per-visit CSV. */

import type { Problem, SolveResult } from "./types";
import { minToClock } from "./format";

function download(filename: string, mime: string, content: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function solutionToGeoJSON(problem: Problem, result: SolveResult): object {
  const stopById = new Map(problem.stops.map((s) => [s.id, s]));
  const features: object[] = [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [problem.depot.lon, problem.depot.lat] },
      properties: { kind: "depot" },
    },
    ...problem.stops.map((s) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      properties: {
        kind: "stop",
        id: s.id,
        demand: s.demand,
        tw_start: s.tw_start,
        tw_end: s.tw_end,
        service_time: s.service_time,
      },
    })),
    ...result.routes
      .filter((r) => r.stop_ids.length > 0)
      .map((r) => ({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [problem.depot.lon, problem.depot.lat],
            ...r.stop_ids.map((id) => {
              const s = stopById.get(id)!;
              return [s.lon, s.lat];
            }),
            [problem.depot.lon, problem.depot.lat],
          ],
        },
        properties: {
          kind: "route",
          vehicle: r.vehicle,
          algorithm: result.algorithm,
          distance_km: r.distance_km,
          duration_min: r.duration_min,
          load: r.load,
          tw_violations: r.tw_violations.length,
        },
      })),
  ];
  return { type: "FeatureCollection", features };
}

export function exportGeoJSON(problem: Problem, result: SolveResult): void {
  download(
    `optiroute-${result.algorithm}.geojson`,
    "application/geo+json",
    JSON.stringify(solutionToGeoJSON(problem, result), null, 2),
  );
}

export function solutionToCSV(problem: Problem, result: SolveResult): string {
  const stopById = new Map(problem.stops.map((s) => [s.id, s]));
  const rows = [
    "vehicle,seq,stop_id,lat,lon,demand,arrival_clock,arrival_min,tw_start,tw_end,late_min",
  ];
  for (const route of result.routes) {
    route.stop_ids.forEach((id, seq) => {
      const s = stopById.get(id)!;
      const arrival = route.arrivals_min[seq];
      const late = s.tw_end !== null && arrival > s.tw_end ? (arrival - s.tw_end).toFixed(1) : "0";
      rows.push(
        [
          route.vehicle,
          seq + 1,
          id,
          s.lat,
          s.lon,
          s.demand,
          minToClock(arrival),
          arrival,
          s.tw_start ?? "",
          s.tw_end ?? "",
          late,
        ].join(","),
      );
    });
  }
  return rows.join("\n");
}

export function exportCSV(problem: Problem, result: SolveResult): void {
  download(`optiroute-${result.algorithm}.csv`, "text/csv", solutionToCSV(problem, result));
}
