import { useState } from "react";
import { clockToMin, minToClock } from "../lib/format";
import type { Stop } from "../lib/types";
import { useStore } from "../state/store";

/**
 * Inline editor anchored to the selected stop: demand, service time, and the
 * time window entered as HH:MM clock times (t=0 on the solver side = 08:00).
 */
export function StopPopover({ stop, x, y }: { stop: Stop; x: number; y: number }) {
  const updateStop = useStore((s) => s.updateStop);
  const removeStop = useStore((s) => s.removeStop);
  const selectStop = useStore((s) => s.selectStop);
  const [twStartText, setTwStartText] = useState(
    stop.tw_start !== null ? minToClock(stop.tw_start) : "",
  );
  const [twEndText, setTwEndText] = useState(stop.tw_end !== null ? minToClock(stop.tw_end) : "");

  function commitWindow(startText: string, endText: string) {
    const tw_start = startText.trim() === "" ? null : clockToMin(startText);
    const tw_end = endText.trim() === "" ? null : clockToMin(endText);
    // Only commit parseable, ordered windows; leave the text for the user to fix otherwise.
    if (startText.trim() !== "" && tw_start === null) return;
    if (endText.trim() !== "" && tw_end === null) return;
    if (tw_start !== null && tw_end !== null && tw_end < tw_start) return;
    updateStop(stop.id, { tw_start, tw_end });
  }

  return (
    <div className="stop-popover" style={{ left: x + 16, top: y - 12 }}>
      <div className="popover-header">
        <strong>Stop {stop.id}</strong>
        <button className="icon-btn" onClick={() => selectStop(null)} title="Close">
          ×
        </button>
      </div>
      <label>
        Demand
        <input
          type="number"
          min={0}
          step={1}
          value={stop.demand}
          onChange={(e) => updateStop(stop.id, { demand: Math.max(0, Number(e.target.value)) })}
        />
      </label>
      <label>
        Service (min)
        <input
          type="number"
          min={0}
          step={1}
          value={stop.service_time}
          onChange={(e) =>
            updateStop(stop.id, { service_time: Math.max(0, Number(e.target.value)) })
          }
        />
      </label>
      <div className="tw-row">
        <label>
          Window from
          <input
            type="text"
            placeholder="08:00"
            value={twStartText}
            onChange={(e) => {
              setTwStartText(e.target.value);
              commitWindow(e.target.value, twEndText);
            }}
          />
        </label>
        <label>
          to
          <input
            type="text"
            placeholder="12:00"
            value={twEndText}
            onChange={(e) => {
              setTwEndText(e.target.value);
              commitWindow(twStartText, e.target.value);
            }}
          />
        </label>
      </div>
      <p className="hint">Clock times; day starts 08:00. Leave blank for no window.</p>
      <button className="danger" onClick={() => removeStop(stop.id)}>
        Delete stop
      </button>
    </div>
  );
}
