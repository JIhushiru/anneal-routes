/**
 * Streaming charts (Recharts). Design per the dataviz method:
 * one measure per axis (temperature gets its OWN chart, never a second y-axis),
 * 2px lines with no point dots, recessive grid, legend for the two-series chart,
 * animations off because data arrives ~30 times per second.
 */

import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { chart } from "../lib/colors";
import { compactInt } from "../lib/format";
import { ALGORITHM_LABELS } from "../lib/types";
import type { Sample } from "../state/store";
import { useStore } from "../state/store";

const MAX_POINTS = 1200;

/** Keep every kth sample plus the last one — enough for a 300px-tall chart. */
function decimate(samples: Sample[]): Sample[] {
  if (samples.length <= MAX_POINTS) return samples;
  const stride = Math.ceil(samples.length / MAX_POINTS);
  const out = samples.filter((_, i) => i % stride === 0);
  if (out[out.length - 1] !== samples[samples.length - 1]) out.push(samples[samples.length - 1]);
  return out;
}

const axisProps = {
  stroke: chart.axis,
  tick: { fill: chart.inkMuted, fontSize: 11 },
  tickLine: false,
} as const;

const tooltipStyle = {
  backgroundColor: chart.surface,
  border: `1px solid ${chart.grid}`,
  borderRadius: 6,
  fontSize: 12,
  color: chart.inkPrimary,
} as const;

export function ConvergenceChart() {
  const run = useStore((s) => s.runs[s.viewRun]);
  const data = useMemo(() => decimate(run.samples), [run.samples]);

  return (
    <div className="chart-card">
      <h3>Convergence — cost vs iteration</h3>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={chart.grid} vertical={false} />
          <XAxis
            dataKey="iteration"
            type="number"
            domain={[0, "dataMax"]}
            tickFormatter={compactInt}
            {...axisProps}
          />
          <YAxis domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(0)} width={44} {...axisProps} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(v) => `iteration ${compactInt(Number(v))}`}
            formatter={(value: number | string, name: string) => [Number(value).toFixed(2), name]}
            isAnimationActive={false}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: chart.inkSecondary }} iconType="plainline" />
          <Line
            name="current cost"
            dataKey="current_cost"
            stroke={chart.currentCost}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            name="best cost"
            dataKey="best_cost"
            stroke={chart.bestCost}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TemperatureChart() {
  const run = useStore((s) => s.runs[s.viewRun]);
  const data = useMemo(
    () => decimate(run.samples.filter((s) => s.temperature !== null)),
    [run.samples],
  );
  if (run.algorithm !== "sa" || data.length === 0) return null;

  return (
    <div className="chart-card">
      <h3>Temperature (geometric cooling)</h3>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={chart.grid} vertical={false} />
          <XAxis
            dataKey="iteration"
            type="number"
            domain={[0, "dataMax"]}
            tickFormatter={compactInt}
            {...axisProps}
          />
          <YAxis
            domain={[0, "auto"]}
            tickFormatter={(v: number) => (v >= 10 ? v.toFixed(0) : v.toFixed(2))}
            width={44}
            {...axisProps}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(v) => `iteration ${compactInt(Number(v))}`}
            formatter={(value: number | string) => [Number(value).toFixed(4), "T"]}
            isAnimationActive={false}
          />
          <Line
            dataKey="temperature"
            stroke={chart.temperature}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Comparison overlay: best cost vs wall-clock, one series per algorithm. */
export function ComparisonChart() {
  const runs = useStore((s) => s.runs);
  const data = useMemo(() => {
    const merge = (key: "A" | "B") =>
      decimate(runs[key].samples).map((s) => ({ elapsed_s: s.elapsed_s, [key]: s.best_cost }));
    return [...merge("A"), ...merge("B")].sort((a, b) => a.elapsed_s - b.elapsed_s);
  }, [runs]);
  if (runs.B.samples.length === 0 && runs.B.status === "idle") return null;

  return (
    <div className="chart-card">
      <h3>Head-to-head — best cost vs time</h3>
      <ResponsiveContainer width="100%" height={170}>
        <LineChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={chart.grid} vertical={false} />
          <XAxis
            dataKey="elapsed_s"
            type="number"
            domain={[0, "dataMax"]}
            tickFormatter={(v: number) => `${v.toFixed(0)}s`}
            {...axisProps}
          />
          <YAxis domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(0)} width={44} {...axisProps} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(v) => `${Number(v).toFixed(1)} s`}
            formatter={(value: number | string, name: string) => [Number(value).toFixed(2), name]}
            isAnimationActive={false}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: chart.inkSecondary }} iconType="plainline" />
          <Line
            name={ALGORITHM_LABELS[runs.A.algorithm ?? "sa"]}
            dataKey="A"
            stroke={chart.comparisonA}
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            name={ALGORITHM_LABELS[runs.B.algorithm ?? "ortools"]}
            dataKey="B"
            stroke={chart.comparisonB}
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
