import { useEffect, useMemo, useRef } from "react";
import { useShallow } from "zustand/react/shallow";
import { Chevron, Retry } from "./Icons";
import { totalTokens, useStore } from "../store";
import type { Filter } from "../store";
import type { Flow, NodeState, RunRecord } from "../types";

const FILTERS: Filter[] = ["all", "running", "failed"];

const MARK: Record<string, string> = {
  input: "IN", agent: "AG", output: "OUT", approval: "APR", workflow: "SUB",
};

/** What the inspector lists: the live run when there is one, else the last run on disk. */
export function nodesOf(run: ReturnType<typeof useStore.getState>["run"],
                        records: RunRecord[], flow?: Flow): NodeState[] {
  if (run?.nodes.length) return run.nodes;
  const live = run?.status === "running" || run?.status === "paused";
  const last = live ? undefined : records[0];   // a live run never shows the last run's statuses
  if (last) {
    return last.nodes.map((n) => ({
      name: n.name, type: n.type || "agent", mode: n.mode || "sync",
      status: (n.status as NodeState["status"]) || (n.failed ? "failed" : n.skipped ? "skipped" : "success"),
      ms: n.ms ?? null, tokens: n.tokens || {}, model: n.model || "", input: n.input || "",
      output: n.output || n.note || "", error: n.error || "", tool_calls: n.tool_calls || [],
      validation: n.validation ?? null, disabled: false,
    }));
  }
  return (flow?.nodes || []).map((n) => ({
    name: n.name, type: n.type || "agent", mode: n.mode || "sync", status: "pending",
    ms: null, tokens: {}, model: n.model || "", input: "", output: "", error: "",
    tool_calls: [], validation: null, disabled: Boolean(n.disabled),
  }));
}

function pretty(text: string) {
  if (!text) return "";
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function Block({ label, body, open = false }: { label: string; body: string; open?: boolean }) {
  if (!body) return null;
  return (
    <details className="block" open={open}>
      <summary><Chevron open={false} /><span className="eyebrow">{label}</span>
        <span className="mono dim">{body.length.toLocaleString()} chars</span></summary>
      <pre className="transcript">{pretty(body)}</pre>
    </details>
  );
}

export default function Inspector() {
  const { run, records, flows, folder, filter, selected, runsError, loadingRuns } = useStore(
    useShallow((s) => ({
      run: s.run, records: s.records, flows: s.flows, folder: s.folder, filter: s.filter,
      selected: s.selected, runsError: s.error.runs, loadingRuns: s.loading.runs,
    })));
  const select = useStore((s) => s.select);
  const setFilter = useStore((s) => s.setFilter);
  const start = useStore((s) => s.start);
  const liveRow = useRef<HTMLLIElement | null>(null);

  const flow = flows.find((f) => f.folder === folder);
  const nodes = useMemo(() => nodesOf(run, records, flow), [run, records, flow]);
  const shown = nodes.filter((n) => filter === "all"
    || (filter === "running" && n.status === "running")
    || (filter === "failed" && n.status === "failed"));

  useEffect(() => {
    liveRow.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [run?.nodes.find((n) => n.status === "running")?.name]);

  return (
    <section className="panel inspector">
      <div className="panel-head">
        <p className="eyebrow">Nodes</p>
        <span className="mono dim">{run ? `run ${run.run_id}` : records[0] ? "last run" : "not run yet"}</span>
        <div className="filters">
          {FILTERS.map((f) => (
            <button key={f} className={`chip ${filter === f ? "is-on" : ""}`} onClick={() => setFilter(f)}>
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="panel-body">
        {runsError && <p className="error-note">{runsError}</p>}
        {loadingRuns && !nodes.length && <p className="loading">reading runs…</p>}
        {!nodes.length && !loadingRuns && <p className="empty">this workflow has no nodes yet</p>}

        <ul className="nodelist">
          {shown.map((node) => {
            const open = selected === node.name;
            const tokens = totalTokens(node.tokens);
            return (
              <li key={node.name} ref={node.status === "running" ? liveRow : undefined}
                  className={`noderow is-${node.status} ${open ? "is-open" : ""} ${node.disabled ? "is-disabled" : ""}`}>
                <button className="noderow-head" onClick={() => select(open ? null : node.name)}>
                  <Chevron open={open} />
                  <span className="mark mono">{MARK[node.type] || "AG"}</span>
                  <span className="nodetext">
                    <span className="nodename">{node.name}</span>
                    <span className="nodemeta mono">
                      <span className={`status is-${node.status}`}>{node.status}</span>
                      <span className="dim">{node.ms == null ? "—" : `${node.ms}ms`}</span>
                      {tokens ? <span className="dim">{tokens.toLocaleString()} tok</span> : null}
                    </span>
                  </span>
                </button>

                {open && (
                  <div className="nodebody">
                    <div className="factline mono">
                      <span>{node.type} · {node.mode}</span>
                      {node.model && <span>model {node.model}</span>}
                      {node.tokens?.prompt ? <span>prompt {node.tokens.prompt}</span> : null}
                      {node.tokens?.completion ? <span>completion {node.tokens.completion}</span> : null}
                    </div>

                    {node.error && (
                      <div className="error-note">
                        {node.error}
                        <div className="retry">
                          <button className="btn small" onClick={() => void start("run", node.name, node.input)}>
                            <Retry /> Retry from this node
                          </button>
                        </div>
                      </div>
                    )}

                    {node.validation && (
                      <div className={`verdict ${node.validation.ok ? "is-ok" : "is-warn"}`}>
                        <span className="eyebrow">Validation</span>
                        {node.validation.ok
                          ? <p className="mono">output held up</p>
                          : <ul className="mini">{node.validation.problems.map((p, i) =>
                              <li key={i} className="mono">{p}</li>)}</ul>}
                      </div>
                    )}

                    <Block label="Input received" body={node.input} />
                    <Block label="Output produced" body={node.output} open />

                    {node.tool_calls.length > 0 && (
                      <details className="block" open>
                        <summary><Chevron open={false} /><span className="eyebrow">Tool calls</span>
                          <span className="mono dim">{node.tool_calls.length}</span></summary>
                        <ul className="calls">
                          {node.tool_calls.map((call, i) => (
                            <li key={i}>
                              <p className="mono callhead">{call.tool}
                                <span className="dim">{call.ms != null ? ` · ${call.ms}ms` : ""}</span></p>
                              <pre className="transcript">{JSON.stringify(call.args, null, 1)}</pre>
                              <pre className="transcript">{String(call.result).slice(0, 1200)}</pre>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}

                    {!node.error && !node.output && node.status === "pending" && (
                      <p className="empty">not run yet</p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        {!shown.length && nodes.length > 0 && <p className="empty">no nodes match this filter</p>}
      </div>
    </section>
  );
}
