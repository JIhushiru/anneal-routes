/**
 * Route/vehicle colors — validated categorical palette (dataviz skill, 2026-07).
 *
 * Same eight hues in two per-surface steppings: LIGHT for polylines drawn over
 * the light map tiles, DARK for swatches/series on the dark panel surface, so a
 * vehicle keeps one hue identity everywhere. Both sets pass the palette
 * validator on their respective surfaces; the light set's sub-3:1 slots get
 * relief from the white polyline casing, and vehicles are always direct-labeled
 * in the results table.
 *
 * Slot ORDER is the colorblind-safety mechanism (maximizes worst adjacent-pair
 * CVD distance) — never re-sort. Fleets can exceed 8 vehicles, so slots repeat
 * with a dash pattern as the secondary (non-color) distinction for lines 9+.
 */

const LIGHT = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"];
const DARK = ["#3987e5", "#199e70", "#c98500", "#008300", "#9085e9", "#e66767", "#d55181", "#d95926"];

export function routeColorMap(vehicle: number): string {
  return LIGHT[vehicle % LIGHT.length];
}

export function routeColorPanel(vehicle: number): string {
  return DARK[vehicle % DARK.length];
}

/** Dash pattern for map polylines: solid for the first 8 vehicles, then dashed/dotted. */
export function routeDashArray(vehicle: number): number[] | undefined {
  const round = Math.floor(vehicle / LIGHT.length);
  if (round === 0) return undefined;
  return round === 1 ? [2, 1.2] : [0.8, 1.2];
}

/** Chart series + chrome tokens (dark panel surface). */
export const chart = {
  surface: "#1a1a19",
  bestCost: DARK[0], // blue
  currentCost: DARK[1], // aqua
  temperature: DARK[4], // violet
  comparisonA: DARK[0],
  comparisonB: DARK[5], // red — max separation from blue
  inkPrimary: "#ffffff",
  inkSecondary: "#c3c2b7",
  inkMuted: "#898781",
  grid: "#2c2c2a",
  axis: "#383835",
} as const;
