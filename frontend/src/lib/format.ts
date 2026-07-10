/** Display helpers. Solver time is minutes from depot departure; the UI renders t=0 as 08:00. */

const DAY_START_MIN = 8 * 60;

export function minToClock(min: number | null | undefined): string {
  if (min === null || min === undefined) return "—";
  const total = Math.round(DAY_START_MIN + min);
  const h = Math.floor(total / 60) % 24;
  const m = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function clockToMin(clock: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(clock.trim());
  if (!m) return null;
  const value = Number(m[1]) * 60 + Number(m[2]) - DAY_START_MIN;
  return value >= 0 ? value : null;
}

export function km(value: number): string {
  return `${value.toFixed(value >= 100 ? 1 : 2)} km`;
}

export function ms(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export function compactInt(value: number): string {
  return value >= 10_000 ? `${(value / 1000).toFixed(0)}k` : String(value);
}
