import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { Bars, Line, Spark, type Point } from "./Charts";
import { Pin } from "./Icons";
import { useStore } from "../store";
import type { MetricDecl, MetricLine } from "../types";

const RANGES: ("24h" | "7d" | "30d")[] = ["24h", "7d", "30d"];

function shape(value: number | null | undefined, format?: string) {
  if (value == null) return "—";
  if (format === "percent") return `${(value <= 1 ? value * 100 : value).toFixed(1)}%`;
  if (format === "ms") return `${Math.round(value)}ms`;
  if (format === "currency") return value.toFixed(2);
  if (format === "count") return String(Math.round(value));
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/** Direction, not judgement: a dashboard cannot know whether up is good. */
function Delta({ now, before, format }: { now: number | null; before: number | null | undefined; format?: string }) {
  if (now == null || before == null || before === 0) return <span className="mono dim">no earlier period</span>;
  const change = ((now - before) / Math.abs(before)) * 100;
  return (
    <span className="mono dim">
      {change >= 0 ? "▲" : "▼"} {Math.abs(change).toFixed(0)}% vs previous · was {shape(before, format)}
    </span>
  );
}

function Tile({ label, value, foot, spark, onPin, onUnpin }: {
  label: string; value: string; foot?: React.ReactNode; spark?: number[];
  onPin?: () => void; onUnpin?: () => void;
}) {
  return (
    <div className="tile">
      <div className="tile-head">
        <p className="eyebrow">{label}</p>
        {onPin && <button className="btn ghost small" title="Pin to Home" onClick={onPin}><Pin /></button>}
        {onUnpin && <button className="btn ghost small" title="Remove from Home" onClick={onUnpin}>×</button>}
      </div>
      <p className="tile-val">{value}</p>
      <div className="tile-foot">
        {foot}
        {spark && spark.length > 1 && <Spark points={spark} />}
      </div>
    </div>
  );
}

const dayOf = (at: number) => new Date(at * 1000).toISOString().slice(5, 10);
const timeOf = (at: number) => new Date(at * 1000).toLocaleString();

function seriesFor(lines: MetricLine[], key: string): Point[] {
  return lines
    .filter((line) => typeof line.values?.[key] === "number")
    .map((line) => ({ label: dayOf(line.at), value: Number(line.values[key]) }));
}

function average(points: Point[]) {
  return points.length ? points.reduce((sum, p) => sum + p.value, 0) / points.length : null;
}

export default function Dashboards() {
  const { flows, dash, loading, error } = useStore(useShallow((s) => ({
    flows: s.flows, dash: s.dash, loading: s.loading.dash, error: s.error.dash,
  })));
  const loadDash = useStore((s) => s.loadDash);
  const pin = useStore((s) => s.pin);
  const unpin = useStore((s) => s.unpin);
  const selectFlow = useStore((s) => s.selectFlow);

  const system = dash.system;
  const previous = system?.previous;
  const runsPerDay: Point[] = system?.per_day ?? [];
  const recent = useMemo(
    () => (dash.folder ? (system?.recent ?? []).filter((r) => r.workflow === dash.folder) : system?.recent ?? []),
    [system, dash.folder]);

  const openInWorkspace = (folder: string) => {
    void selectFlow(folder);
    history.pushState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  return (
    <main className="dashboards">
      <div className="dashbar">
        <label className="field-inline">
          <span className="eyebrow">Workflow</span>
          <select value={dash.folder ?? ""} onChange={(e) => void loadDash(e.target.value || null)}>
            <option value="">all workflows</option>
            {flows.map((f) => <option key={f.folder} value={f.folder}>{f.name}</option>)}
          </select>
        </label>
        <div className="toggle">
          {RANGES.map((range) => (
            <button key={range} className={`chip ${dash.range === range ? "is-on" : ""}`}
                    onClick={() => void loadDash(undefined, range)}>{range}</button>
          ))}
        </div>
        <span className="mono dim">{loading ? "reading history…" : `${system?.runs ?? 0} runs in range`}</span>
      </div>

      {error && <p className="error-note">{error}</p>}

      {dash.home.length > 0 && (
        <section className="dashsection">
          <p className="eyebrow">Home</p>
          <div className="tiles">
            {dash.home.map((widget) => {
              const data = (widget.data || {}) as { value?: unknown; foot?: string; empty?: string;
                                                    error?: string; series?: Point[]; tiles?: { label: string; value: string; foot: string }[] };
              if (data.tiles) {
                return data.tiles.map((t, i) => (
                  <Tile key={widget.id + t.label} label={t.label} value={String(t.value)}
                        foot={<span className="mono dim">{t.foot}</span>}
                        onUnpin={i === 0 ? () => void unpin(widget.id) : undefined} />
                ));
              }
              if (data.series) {
                return (
                  <div className="widecard" key={widget.id}>
                    <div className="tile-head">
                      <p className="eyebrow">{widget.title || widget.kind}</p>
                      <button className="btn ghost small" title="Remove from Home"
                              onClick={() => void unpin(widget.id)}>×</button>
                    </div>
                    <Bars points={data.series} />
                  </div>
                );
              }
              return (
                <Tile key={widget.id} label={widget.title || widget.kind}
                      value={String(data.value ?? data.empty ?? data.error ?? "—")}
                      foot={<span className="mono dim">{data.foot || widget.workflow || ""}</span>}
                      onUnpin={() => void unpin(widget.id)} />
              );
            })}
          </div>
        </section>
      )}

      <section className="dashsection">
        <p className="eyebrow">All workflows</p>
        <div className="tiles">
          <Tile label="Runs" value={String(system?.runs ?? 0)}
                foot={<Delta now={system?.runs ?? 0} before={previous?.runs} />}
                spark={runsPerDay.map((p) => p.value)}
                onPin={() => void pin({ id: "sys-runs", kind: "stat", title: "Runs",
                                        workflow: dash.folder || flows[0]?.folder, metric: "runs" })} />
          <Tile label="Success rate"
                value={system?.success_rate == null ? "—" : `${(system.success_rate * 100).toFixed(0)}%`}
                foot={<Delta now={system?.success_rate ?? null} before={previous?.success_rate} format="percent" />} />
          <Tile label="Average duration" value={shape(system?.avg_ms ?? null, "ms")}
                foot={<Delta now={system?.avg_ms ?? null} before={previous?.avg_ms} format="ms" />} />
          <Tile label="Tokens used" value={(system?.tokens ?? 0).toLocaleString()}
                foot={<Delta now={system?.tokens ?? 0} before={previous?.tokens} />} />
        </div>

        <div className="cards">
          <div className="widecard">
            <p className="eyebrow">Runs per day</p>
            <Bars points={runsPerDay} />
          </div>
          <div className="widecard">
            <p className="eyebrow">Failures by node</p>
            {system?.failures_by_node.length
              ? <Bars points={system.failures_by_node} />
              : <p className="empty">no failed nodes in this range</p>}
          </div>
        </div>
      </section>

      {dash.folder && (
        <section className="dashsection">
          <p className="eyebrow">{flows.find((f) => f.folder === dash.folder)?.name} · declared metrics</p>
          {dash.declared.length === 0 && (
            <p className="empty">
              this workflow declares no metrics. Add them to its yaml:
              {" "}<code className="mono">metrics: [&#123; key: confidence, label: Avg Confidence, agg: avg, format: percent &#125;]</code>
            </p>
          )}
          <div className="tiles">
            {dash.declared.map((metric: MetricDecl) => {
              const points = seriesFor(dash.lines, metric.key);
              return (
                <Tile key={metric.key} label={metric.label || metric.key}
                      value={shape(average(points), metric.format)}
                      foot={<span className="mono dim">{points.length} run(s) · {metric.agg || "avg"}</span>}
                      spark={points.map((p) => p.value)}
                      onPin={() => void pin({ id: `m-${dash.folder}-${metric.key}`, kind: "stat",
                                              title: metric.label || metric.key, metric: "field",
                                              workflow: dash.folder!, field: metric.key,
                                              agg: metric.agg })} />
              );
            })}
          </div>
          <div className="cards">
            {dash.declared.map((metric: MetricDecl) => {
              const points = seriesFor(dash.lines, metric.key);
              return (
                <div className="widecard" key={`c-${metric.key}`}>
                  <p className="eyebrow">{metric.label || metric.key} over time</p>
                  <Line points={points} format={(v) => shape(v, metric.format)} />
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="dashsection">
        <p className="eyebrow">Recent runs</p>
        {recent.length === 0 ? (
          <p className="empty">no runs in this range yet</p>
        ) : (
          <table className="runs">
            <thead>
              <tr><th>When</th><th>Workflow</th><th>Status</th><th>Duration</th><th>Records</th><th>Key outputs</th><th /></tr>
            </thead>
            <tbody>
              {recent.map((line) => (
                <tr key={line.run_id + line.at}>
                  <td className="mono">{timeOf(line.at)}</td>
                  <td className="mono">{line.name || line.workflow}</td>
                  <td className={`mono status is-${line.status === "completed" ? "success" : line.status}`}>
                    {line.status}
                  </td>
                  <td className="mono">{line.ms}ms</td>
                  <td className="mono">{line.records}</td>
                  <td className="mono">
                    {Object.entries(line.values || {}).map(([key, value]) =>
                      `${key} ${shape(value as number)}`).join(" · ") || "—"}
                  </td>
                  <td>
                    <button className="btn small" onClick={() => openInWorkspace(line.workflow)}>open</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
