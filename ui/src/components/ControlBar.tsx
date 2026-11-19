import { useEffect, useState } from "react";
import { Flask, Pause, Play, Stop } from "./Icons";
import { useShallow } from "zustand/react/shallow";
import { totalTokens, useStore } from "../store";
import type { RunStatus } from "../types";

const LABEL: Record<RunStatus, string> = {
  idle: "Idle", running: "Running", paused: "Paused", failed: "Failed",
  completed: "Completed", stopped: "Stopped",
};

function elapsed(from: number, to: number | null) {
  const ms = Math.max(0, ((to ?? Date.now() / 1000) - from) * 1000);
  const whole = Math.floor(ms / 1000);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

export default function ControlBar() {
  const { flows, folder, run, records, connection, controlError } = useStore(useShallow((s) => ({
    flows: s.flows, folder: s.folder, run: s.run, records: s.records,
    connection: s.connection, controlError: s.error.control,
  })));
  const selectFlow = useStore((s) => s.selectFlow);
  const start = useStore((s) => s.start);
  const control = useStore((s) => s.control);
  const [, tick] = useState(0);

  const running = run?.status === "running";
  const paused = run?.status === "paused";
  const busy = running || paused;

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const flow = flows.find((f) => f.folder === folder);
  const status: RunStatus = run?.status ?? "idle";
  const last = records[0];
  const tokens = totalTokens(run?.tokens) || records.slice(0, 1).reduce((n, r) => n + totalTokens(r.tokens), 0);

  return (
    <div className="controlbar">
      <label className="field-inline">
        <span className="eyebrow">Workflow</span>
        <select value={folder ?? ""} disabled={!flows.length || busy}
                onChange={(e) => void selectFlow(e.target.value)}>
          {!flows.length && <option value="">no workflows yet</option>}
          {flows.map((f) => (
            <option key={f.folder} value={f.folder}>{f.name}</option>
          ))}
        </select>
      </label>

      <span className="flowname display">{flow?.name ?? "—"}</span>
      <span className={`pill is-${status}`}>{LABEL[status]}</span>
      {run?.mode === "test" && <span className="pill is-test">Test</span>}
      {flow?.problems.length ? (
        <span className="pill is-warn" title={flow.problems.join("\n")}>{flow.problems.length} warn</span>
      ) : null}

      <div className="controls">
        <button className="btn primary" disabled={!folder || busy} onClick={() => void start("run")}
                title="Start a full run with real tools (Space)">
          <Play /> Start
        </button>
        <button className="btn" disabled={!busy} onClick={() => void control(paused ? "resume" : "pause")}
                title="Finish this node, then hold (Space)">
          {paused ? <Play /> : <Pause />} {paused ? "Resume" : "Pause"}
        </button>
        <button className="btn danger" disabled={!busy} onClick={() => void control("stop")}
                title="Cancel the run, mark the rest cancelled (Esc)">
          <Stop /> Stop
        </button>
        <button className="btn" disabled={!folder || busy} onClick={() => void start("test")}
                title="Dry run: side effects are mocked (T)">
          <Flask /> Test
        </button>
      </div>

      <div className="readout">
        {controlError && <span className="readout-err mono" role="alert">{controlError}</span>}
        <span className={`conn is-${connection}`} title={`event stream ${connection}`} />
        <span className="mono">{run ? `run ${run.run_id}` : "no run"}</span>
        <span className="mono">{run ? elapsed(run.started, run.finished) : "--:--"}</span>
        <span className="mono">{tokens ? `${tokens.toLocaleString()} tok` : "0 tok"}</span>
        <span className="mono dim">{last ? `last ${last.started}` : "never run"}</span>
      </div>
    </div>
  );
}
