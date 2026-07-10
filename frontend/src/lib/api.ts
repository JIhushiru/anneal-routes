import type { Problem, ScenarioSummary, ServerEvent, SolveParams, SolveResult } from "./types";

export async function fetchScenarios(): Promise<ScenarioSummary[]> {
  const resp = await fetch("/api/scenarios");
  if (!resp.ok) throw new Error(`scenarios request failed: ${resp.status}`);
  return resp.json();
}

export async function solveSync(problem: Problem, params: SolveParams): Promise<SolveResult> {
  const resp = await fetch("/api/solve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "solve", problem, params }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail ?? `solve failed: ${resp.status}`);
  }
  return resp.json();
}

export interface StreamHandle {
  cancel(): void;
}

/**
 * Open a WebSocket solve. Events arrive already coalesced to ~30 fps by the
 * server. `onEvent` receives every progress frame plus the terminal done/error.
 *
 * cancel() is terminal for the stream: it tells the server to stop, closes the
 * socket, and guarantees `onEvent` is NEVER called again — so a cancelled run
 * can't write stale events into state that a newer run now owns.
 */
export function solveStream(
  problem: Problem,
  params: SolveParams,
  onEvent: (event: ServerEvent) => void,
): StreamHandle {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/solve`);
  let settled = false;

  ws.onopen = () => ws.send(JSON.stringify({ type: "solve", problem, params }));
  ws.onmessage = (msg) => {
    if (settled) return;
    const event: ServerEvent = JSON.parse(msg.data);
    if (event.type === "done" || event.type === "error") {
      settled = true;
      ws.close();
    }
    onEvent(event);
  };
  ws.onerror = () => {
    if (!settled) {
      settled = true;
      onEvent({ type: "error", message: "WebSocket connection failed — is the backend running?" });
    }
  };
  ws.onclose = () => {
    if (!settled) {
      settled = true;
      onEvent({ type: "error", message: "connection closed before the solve finished" });
    }
  };

  return {
    cancel() {
      if (settled) return;
      settled = true; // no further onEvent deliveries, whatever the server sends
      if (ws.readyState !== WebSocket.OPEN) {
        ws.close(); // aborts a still-CONNECTING socket before the solve is sent
        return;
      }
      try {
        ws.send(JSON.stringify({ type: "cancel" }));
      } catch {
        // fall through to the close below
      }
      // Let the server finish its close handshake (it stops the solver, sends
      // the final frame, then closes). Slamming the socket shut while it is
      // still writing surfaces as ECONNRESET noise in the dev proxy. The
      // timeout force-closes only if the server never gets there.
      const fallback = window.setTimeout(() => ws.close(), 2000);
      ws.addEventListener("close", () => window.clearTimeout(fallback));
    },
  };
}
