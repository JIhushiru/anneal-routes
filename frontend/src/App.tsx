import { ComparisonChart, ConvergenceChart, TemperatureChart } from "./components/charts";
import { ComparisonPanel } from "./components/ComparisonPanel";
import { MapView } from "./components/MapView";
import { ResultsPanel } from "./components/ResultsPanel";
import { SolverPanel } from "./components/SolverPanel";
import { useStore } from "./state/store";

export default function App() {
  const comparisonMode = useStore((s) => s.comparisonMode);
  const hasSamples = useStore((s) => s.runs.A.samples.length > 0);

  return (
    <div className="app">
      <header className="app-header">
        <h1>
          OptiRoute <span className="ph">PH</span>
        </h1>
        <p>capacitated vehicle routing with time windows — watch the solver think</p>
      </header>
      <div className="app-body">
        <aside className="sidebar">
          <SolverPanel />
          {comparisonMode && <ComparisonPanel />}
          <ResultsPanel />
        </aside>
        <main className="main-col">
          <MapView />
          {hasSamples && (
            <div className="charts-strip">
              <ConvergenceChart />
              <TemperatureChart />
              {comparisonMode && <ComparisonChart />}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
