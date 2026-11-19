/** One store. Every panel reads from this; nothing keeps a second copy of a run. */
import { create } from "zustand";
import * as api from "./api";
import type {
  Diff, Flow, MetricDecl, MetricLine, NodeState, Proposal, RunEvent, RunRecord, RunState,
  SystemMetrics, Tokens,
} from "./types";

export type Filter = "all" | "running" | "failed";
export type Theme = "light" | "dark";
export type Connection = "idle" | "open" | "closed";
export type CanvasSource = "live" | "last";

export interface ChatMessage {
  who: "you" | "awo";
  text: string;
  at: number;
  pending?: boolean;
}

const EVENT_TRAIL = 400;

function blankRun(folder: string, run_id: string): RunState {
  return {
    run_id, workflow: folder, name: "", mode: "run", status: "running", from_node: "",
    started: Date.now() / 1000, finished: null, ms: null, tokens: {}, metrics: {}, error: "",
    seq: 0, nodes: [],
  };
}

/** The same fold the server does in runner.RunState.apply, so both tell one story. */
export function reduce(run: RunState | null, event: RunEvent): RunState | null {
  if (event.type === "heartbeat") return run;
  // Only a run_started may replace the run on screen. Anything else about another run is
  // a late line from a finished one, and folding it in would rewrite the live run.
  if (run && run.run_id !== event.run_id && event.type !== "run_started") return run;
  let next: RunState = run && run.run_id === event.run_id
    ? { ...run, nodes: run.nodes.map((n) => ({ ...n })) }
    : blankRun(event.workflow, event.run_id);
  next.seq = Math.max(next.seq, event.seq);
  const node: NodeState | undefined = next.nodes.find((n) => n.name === event.node);

  switch (event.type) {
    case "run_started":
      next = {
        ...next,
        mode: (event.mode as RunState["mode"]) || "run",
        from_node: event.from_node || "",
        status: "running",
        started: event.at || next.started,
        nodes: event.nodes.map((n) => ({
          name: n.name, type: n.type || "agent", mode: n.mode || "sync",
          status: "pending", ms: null, tokens: {}, model: "", input: "", output: "",
          error: "", tool_calls: [], validation: null, disabled: Boolean(n.disabled),
        })),
      };
      break;
    case "node_started":
      if (node) { node.status = "running"; node.input = event.text || ""; }
      break;
    case "node_output":
      if (node) node.output = event.text || "";
      break;
    case "tool_call":
      if (node) {
        node.tool_calls = [...node.tool_calls,
          { tool: event.tool, args: event.args, result: event.result, ms: event.ms }];
      }
      break;
    case "node_completed":
      if (node) {
        node.status = (event.status as NodeState["status"]) || "success";
        node.ms = event.ms;
        node.tokens = event.tokens || {};
        node.model = event.model || "";
        node.validation = event.validation;
      }
      break;
    case "node_failed":
      if (node) { node.status = "failed"; node.ms = event.ms; node.error = event.error || ""; }
      break;
    case "run_paused": next.status = "paused"; break;
    case "run_resumed": next.status = "running"; break;
    case "run_stopped": next.status = "stopped"; break;
    case "run_completed":
      next.status = (event.status as RunState["status"]) || "completed";
      next.ms = event.ms;
      next.tokens = event.tokens || {};
      next.metrics = event.metrics || {};
      next.error = event.error || "";
      next.finished = event.at;
      break;
  }
  return next;
}

export interface Panels { left: boolean; right: boolean; leftWidth: number; rightWidth: number }

interface Store {
  flows: Flow[];
  folder: string | null;
  yaml: string;
  records: RunRecord[];
  run: RunState | null;
  events: RunEvent[];
  selected: string | null;
  filter: Filter;
  canvasSource: CanvasSource;
  connection: Connection;
  theme: Theme;
  panels: Panels;
  loading: { flows: boolean; runs: boolean; chat: boolean; dash: boolean };
  error: { flows?: string; runs?: string; chat?: string; dash?: string; control?: string };
  chat: ChatMessage[];
  proposal: Proposal | null;
  versions: { version: string; at: number; label: string; bytes: number }[];
  dash: {
    folder: string | null;
    range: "24h" | "7d" | "30d";
    declared: MetricDecl[];
    lines: MetricLine[];
    system: SystemMetrics | null;
    home: { id: string; kind: string; title?: string; workflow?: string; metric?: string;
            data?: Record<string, unknown> }[];
  };

  load: (folder?: string) => Promise<void>;
  selectFlow: (folder: string) => Promise<void>;
  loadRuns: () => Promise<void>;
  applyEvent: (event: RunEvent) => void;
  setConnection: (state: Connection) => void;
  adoptRun: (run: RunState | null) => void;
  start: (mode: "run" | "test", fromNode?: string, input?: string) => Promise<void>;
  control: (action: "pause" | "resume" | "stop") => Promise<void>;
  select: (node: string | null) => void;
  setFilter: (filter: Filter) => void;
  setCanvasSource: (source: CanvasSource) => void;
  togglePanel: (side: "left" | "right") => void;
  setPanelWidth: (side: "left" | "right", width: number) => void;
  setTheme: (theme: Theme) => void;
  say: (message: ChatMessage) => void;
  propose: (message: string, scopeToNode: boolean) => Promise<void>;
  applyProposal: () => Promise<void>;
  discardProposal: () => void;
  loadVersions: () => Promise<void>;
  restore: (version: string) => Promise<void>;
  nodeAction: (action: "disable" | "duplicate" | "delete" | "move",
               name: string, extra?: { x: number; y: number }) => Promise<void>;
  ask: (question: string) => Promise<void>;
  loadDash: (folder?: string | null, range?: "24h" | "7d" | "30d") => Promise<void>;
  pin: (widget: { id: string; kind: string; title: string; workflow?: string; metric?: string;
                  field?: string; agg?: string }) => Promise<void>;
  unpin: (id: string) => Promise<void>;
}

const savedTheme = (localStorage.getItem("awo-theme") as Theme | null) || "light";

export const useStore = create<Store>()((set, store) => ({
  flows: [],
  folder: null,
  yaml: "",
  records: [],
  run: null,
  events: [],
  selected: null,
  filter: "all",
  canvasSource: "live",
  connection: "idle",
  theme: savedTheme,
  panels: {
    left: true,
    right: true,
    leftWidth: Number(localStorage.getItem("awo-left") || 300),
    rightWidth: Number(localStorage.getItem("awo-right") || 360),
  },
  loading: { flows: false, runs: false, chat: false, dash: false },
  error: {},
  chat: [],
  proposal: null,
  versions: [],
  dash: { folder: null, range: "7d", declared: [], lines: [], system: null, home: [] },

  async load(folder) {
    set((s) => ({ loading: { ...s.loading, flows: true }, error: { ...s.error, flows: undefined } }));
    try {
      const flows = await api.get<Flow[]>("/api/workflows");
      const pick = folder || store().folder || flows[0]?.folder || null;
      set({ flows, folder: pick });
      if (pick) await store().loadRuns();
    } catch (e) {
      set((s) => ({ error: { ...s.error, flows: (e as Error).message } }));
    } finally {
      set((s) => ({ loading: { ...s.loading, flows: false } }));
    }
  },

  async selectFlow(folder) {
    set({ folder, run: null, events: [], selected: null, proposal: null, versions: [] });
    await store().loadRuns();
  },

  async loadRuns() {
    const folder = store().folder;
    if (!folder) return;
    set((s) => ({ loading: { ...s.loading, runs: true }, error: { ...s.error, runs: undefined } }));
    try {
      const [records, yamlBody, active] = await Promise.all([
        api.get<RunRecord[]>(`/api/runs?w=${api.q(folder)}`),
        api.get<{ yaml: string }>(`/api/yaml?w=${api.q(folder)}`),
        api.get<{ run: RunState | null }>(`/api/active?w=${api.q(folder)}`),
      ]);
      set({ records, yaml: yamlBody.yaml || "", run: active.run ?? store().run });
    } catch (e) {
      set((s) => ({ error: { ...s.error, runs: (e as Error).message } }));
    } finally {
      set((s) => ({ loading: { ...s.loading, runs: false } }));
    }
  },

  applyEvent(event) {
    set((s) => {
      if (s.folder && event.workflow && event.workflow !== s.folder) return s;
      if (s.run && s.run.run_id !== event.run_id && event.type !== "run_started") return s;
      const run = reduce(s.run, event);
      const events = event.type === "heartbeat" ? s.events
        : [...s.events, event].slice(-EVENT_TRAIL);
      const selected = s.selected ?? (event.type === "node_started" ? event.node : null);
      return { ...s, run, events, selected };
    });
    if (event.type === "run_completed") void store().loadRuns();
  },

  setConnection(state) { set({ connection: state }); },
  adoptRun(run) { set({ run }); },

  async start(mode, fromNode, input) {
    const folder = store().folder;
    if (!folder) return;
    set((s) => ({ error: { ...s.error, control: undefined } }));
    try {
      const out = await api.post<{ success: boolean; run?: RunState; error?: string }>(
        "/api/run", { folder, mode, from_node: fromNode, input });
      if (!out.success) {
        set((s) => ({ error: { ...s.error, control: out.error } }));
        return;
      }
      // The first events can beat this reply back. Never overwrite a run the stream already started.
      set((s) => (s.run && out.run && s.run.run_id === out.run.run_id
        ? { events: s.events }
        : { run: out.run ?? null, events: [] }));
    } catch (e) {
      set((s) => ({ error: { ...s.error, control: (e as Error).message } }));
    }
  },

  async control(action) {
    const run = store().run;
    if (!run) return;
    try {
      const out = await api.post<{ success: boolean; error?: string }>(
        "/api/control", { run_id: run.run_id, action });
      if (!out.success) set((s) => ({ error: { ...s.error, control: out.error } }));
    } catch (e) {
      set((s) => ({ error: { ...s.error, control: (e as Error).message } }));
    }
  },

  select(node) { set({ selected: node }); },
  setFilter(filter) { set({ filter }); },
  setCanvasSource(source) { set({ canvasSource: source }); },

  togglePanel(side) {
    set((s) => ({ panels: { ...s.panels, [side]: !s.panels[side] } }));
  },

  setPanelWidth(side, width) {
    const clamped = Math.max(220, Math.min(620, Math.round(width)));
    localStorage.setItem(side === "left" ? "awo-left" : "awo-right", String(clamped));
    set((s) => ({ panels: { ...s.panels, [side === "left" ? "leftWidth" : "rightWidth"]: clamped } }));
  },

  setTheme(theme) {
    localStorage.setItem("awo-theme", theme);
    document.documentElement.dataset.theme = theme;
    set({ theme });
  },

  say(message) { set((s) => ({ chat: [...s.chat, message] })); },

  async propose(message, scopeToNode) {
    const folder = store().folder;
    set((s) => ({ loading: { ...s.loading, chat: true }, error: { ...s.error, chat: undefined } }));
    store().say({ who: "you", text: message, at: Date.now() });
    try {
      const out = await api.post<Proposal>("/api/chat", {
        message, folder, propose: true,
        node: scopeToNode ? store().selected : undefined,
      });
      if (out.success) {
        set({ proposal: out });
        const counts = out.diff?.counts;
        store().say({
          who: "awo", at: Date.now(),
          text: counts
            ? `proposed: ${counts.added} added, ${counts.modified} modified, ${counts.removed} removed`
            : "proposed a workflow",
        });
      } else {
        set((s) => ({ error: { ...s.error, chat: out.error } }));
        store().say({ who: "awo", text: `failed: ${out.error}`, at: Date.now() });
      }
    } catch (e) {
      set((s) => ({ error: { ...s.error, chat: (e as Error).message } }));
    } finally {
      set((s) => ({ loading: { ...s.loading, chat: false } }));
    }
  },

  async applyProposal() {
    const { proposal, folder } = store();
    if (!proposal?.yaml) return;
    try {
      if (folder && proposal.current !== undefined) {
        const out = await api.post<{ success: boolean; error?: string; warnings?: string[] }>(
          "/api/apply", { folder, yaml: proposal.yaml });
        if (!out.success) {
          store().say({ who: "awo", text: `could not apply: ${out.error}`, at: Date.now() });
          return;
        }
        store().say({
          who: "awo", at: Date.now(),
          text: `applied${out.warnings?.length ? ` · ${out.warnings.length} warning(s)` : ""}`,
        });
        set({ proposal: null });
        await store().load(folder);
        await store().loadVersions();
      } else {
        const out = await api.post<{ success: boolean; folder?: string; error?: string }>(
          "/api/create", { yaml: proposal.yaml });
        store().say({ who: "awo", text: out.success ? `created ${out.folder}` : `failed: ${out.error}`, at: Date.now() });
        set({ proposal: null });
        await store().load(out.folder);
      }
    } catch (e) {
      store().say({ who: "awo", text: `could not apply: ${(e as Error).message}`, at: Date.now() });
    }
  },

  discardProposal() { set({ proposal: null }); },

  async loadVersions() {
    const folder = store().folder;
    if (!folder) return;
    try {
      const out = await api.get<{ versions: Store["versions"] }>(`/api/versions?w=${api.q(folder)}`);
      set({ versions: out.versions });
    } catch { /* versions are a convenience, never a blocker */ }
  },

  async restore(version) {
    const folder = store().folder;
    if (!folder) return;
    const out = await api.post<{ success: boolean; error?: string }>("/api/restore", { folder, version });
    store().say({ who: "awo", text: out.success ? `restored ${version}` : `failed: ${out.error}`, at: Date.now() });
    await store().load(folder);
    await store().loadVersions();
  },

  async nodeAction(action, name, extra) {
    const folder = store().folder;
    if (!folder) return;
    const out = await api.post<{ success: boolean; error?: string }>(
      "/api/node", { folder, action, name, ...(extra || {}) });
    if (!out.success) store().say({ who: "awo", text: `failed: ${out.error}`, at: Date.now() });
    if (action !== "move") await store().load(folder);
  },

  async pin(widget) {
    await api.post("/api/board/pin", { widget });
    await store().loadDash();
  },

  async unpin(id) {
    const board = await api.get<{ widgets: { id: string }[] }>("/api/board");
    await api.post("/api/board", { widgets: (board.widgets || []).filter((w) => w.id !== id) });
    await store().loadDash();
  },

  async ask(question) {
    const folder = store().folder;
    if (!folder) return;
    store().say({ who: "you", text: question, at: Date.now() });
    set((s) => ({ loading: { ...s.loading, chat: true } }));
    try {
      const out = await api.post<{ success: boolean; answer?: string; error?: string }>(
        "/api/ask", { folder, question });
      store().say({ who: "awo", text: out.success ? out.answer || "" : `failed: ${out.error}`, at: Date.now() });
    } catch (e) {
      store().say({ who: "awo", text: `failed: ${(e as Error).message}`, at: Date.now() });
    } finally {
      set((s) => ({ loading: { ...s.loading, chat: false } }));
    }
  },

  async loadDash(folder, range) {
    const chosen = folder === undefined ? store().dash.folder : folder;
    const window = range || store().dash.range;
    set((s) => ({ loading: { ...s.loading, dash: true }, error: { ...s.error, dash: undefined },
                  dash: { ...s.dash, folder: chosen, range: window } }));
    try {
      const [system, home] = await Promise.all([
        api.get<SystemMetrics>(`/api/metrics/system?range=${window}`),
        api.get<{ widgets: Store["dash"]["home"] }>("/api/board/data"),
      ]);
      let declared: MetricDecl[] = [];
      let lines: MetricLine[] = [];
      if (chosen) {
        const own = await api.get<{ declared: MetricDecl[]; lines: MetricLine[] }>(
          `/api/metrics?w=${api.q(chosen)}&range=${window}`);
        declared = own.declared;
        lines = own.lines;
      }
      set((s) => ({ dash: { ...s.dash, system, declared, lines, home: home.widgets || [] } }));
    } catch (e) {
      set((s) => ({ error: { ...s.error, dash: (e as Error).message } }));
    } finally {
      set((s) => ({ loading: { ...s.loading, dash: false } }));
    }
  },
}));

export const totalTokens = (tokens: Tokens | undefined) =>
  tokens?.total ?? ((tokens?.prompt || 0) + (tokens?.completion || 0));

export const diffStatus = (diff: Diff | undefined, name: string) =>
  diff?.nodes.find((n) => n.name === name)?.status;
