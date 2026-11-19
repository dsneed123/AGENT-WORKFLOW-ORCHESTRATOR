import { useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { Flask } from "./Icons";
import { useStore } from "../store";

const QUICK = [
  { label: "Explain this workflow", question: "Explain what this workflow does, step by step." },
  { label: "Why did this fail?", question: "Why did the last run fail or produce a poor result, and what should change?" },
  { label: "Optimize tokens", question: "Where is this workflow wasting tokens, and what would you cut?" },
];

export default function Chat() {
  const { chat, proposal, folder, selected, busy, versions, chatError } = useStore(useShallow((s) => ({
    chat: s.chat, proposal: s.proposal, folder: s.folder, selected: s.selected,
    busy: s.loading.chat, versions: s.versions, chatError: s.error.chat,
  })));
  const propose = useStore((s) => s.propose);
  const ask = useStore((s) => s.ask);
  const applyProposal = useStore((s) => s.applyProposal);
  const discard = useStore((s) => s.discardProposal);
  const loadVersions = useStore((s) => s.loadVersions);
  const restore = useStore((s) => s.restore);
  const start = useStore((s) => s.start);
  const [text, setText] = useState("");
  const [scoped, setScoped] = useState(true);
  const [showVersions, setShowVersions] = useState(false);
  const [justApplied, setJustApplied] = useState(false);
  const log = useRef<HTMLDivElement | null>(null);

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }); }, [chat.length, busy]);
  useEffect(() => { if (folder) void loadVersions(); }, [folder, loadVersions]);

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setJustApplied(false);
    await propose(message, scoped && Boolean(selected));
  };

  const apply = async () => {
    await applyProposal();
    setJustApplied(true);
  };

  return (
    <section className="panel chat">
      <div className="panel-head">
        <p className="eyebrow">Build with chat</p>
        <button className="btn ghost small" onClick={() => setShowVersions((v) => !v)}>
          history{versions.length ? ` (${versions.length})` : ""}
        </button>
      </div>

      {selected && scoped && (
        <p className="scope mono">Editing: <b>{selected}</b>
          <button className="chip" onClick={() => setScoped(false)}>whole workflow</button></p>
      )}
      {selected && !scoped && (
        <p className="scope mono">Editing: whole workflow
          <button className="chip" onClick={() => setScoped(true)}>just {selected}</button></p>
      )}

      {showVersions && (
        <div className="versions">
          {versions.length === 0 && <p className="empty">no versions kept yet</p>}
          <ul className="mini">
            {versions.map((v) => (
              <li key={v.version} className="versionrow">
                <span className="mono">{v.version.replace(".yaml", "")}</span>
                <button className="btn small" onClick={() => void restore(v.version)}>restore</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="chatlog panel-body" ref={log}>
        {chat.length === 0 && (
          <p className="empty">
            ask for a change: “add a node that summarises before the email draft”,
            “make the stock node return a confidence score 0–100”, “retry twice on failure”
          </p>
        )}
        {chat.map((message, i) => (
          <div key={i} className={`msg ${message.who === "you" ? "me" : "awo"}`}>
            <span className="who mono">{message.who}</span>
            <p>{message.text}</p>
          </div>
        ))}
        {busy && <p className="loading">thinking on a local model, this takes a minute…</p>}
        {chatError && <p className="error-note">{chatError}</p>}
      </div>

      {proposal?.diff && (
        <div className="proposal">
          <div className="panel-head">
            <p className="eyebrow">Proposed change</p>
            <span className="mono dim">
              +{proposal.diff.counts.added} ~{proposal.diff.counts.modified} −{proposal.diff.counts.removed}
            </span>
          </div>
          <ul className="mini difflist">
            {proposal.diff.nodes.map((node) => (
              <li key={node.name} className={`diffrow d-${node.status}`}>
                <span className="mono">{node.status === "added" ? "+" : node.status === "removed" ? "−" : "~"} {node.name}</span>
                {node.changes && (
                  <span className="mono dim"> {Object.keys(node.changes).slice(0, 4).join(", ")}</span>
                )}
              </li>
            ))}
            {proposal.diff.edges.map((edge, i) => (
              <li key={`e${i}`} className={`diffrow d-${edge.status}`}>
                <span className="mono">{edge.status === "added" ? "+" : "−"} edge {edge.from} → {edge.to}</span>
              </li>
            ))}
            {Object.entries(proposal.diff.top).map(([field, pair]) => (
              <li key={field} className="diffrow d-modified">
                <span className="mono">~ {field}: {String(pair[0]).slice(0, 24)} → {String(pair[1]).slice(0, 24)}</span>
              </li>
            ))}
          </ul>
          {proposal.warnings?.length ? (
            <p className="warnline mono">{proposal.warnings.length} warning(s): {proposal.warnings[0]}</p>
          ) : null}
          <details className="block">
            <summary><span className="eyebrow">Proposed yaml</span></summary>
            <pre className="transcript">{proposal.yaml}</pre>
          </details>
          <div className="proposal-actions">
            <button className="btn primary" onClick={() => void apply()}>Apply</button>
            <button className="btn" onClick={discard}>Discard</button>
          </div>
        </div>
      )}

      {justApplied && !proposal && (
        <div className="proposal-actions">
          <button className="btn" onClick={() => { setJustApplied(false); void start("test"); }}>
            <Flask /> Run Test now
          </button>
        </div>
      )}

      <div className="quick">
        {QUICK.map((action) => (
          <button key={action.label} className="chip" disabled={busy || !folder}
                  onClick={() => void ask(action.question)}>{action.label}</button>
        ))}
      </div>

      <form className="chatform" onSubmit={send}>
        <textarea rows={3} value={text} placeholder="add a node that summarises before the email draft"
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send(e); }} />
        <div className="chatrow">
          <span className="mono dim">{folder ? "edits this workflow" : "creates a new workflow"}</span>
          <button className="btn primary" type="submit" disabled={busy}>Send</button>
        </div>
      </form>
    </section>
  );
}
