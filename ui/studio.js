const $ = (id) => document.getElementById(id);
const esc = (v) => String(v == null ? "" : v).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const state = { flows: [], folder: null, runs: [], view: "canvas", yaml: "", board: null, adding: false };

const params = new URLSearchParams(location.search);
if (params.get("api")) localStorage.setItem("awo-api", params.get("api").replace(/\/$/, ""));
if (params.get("token")) localStorage.setItem("awo-token", params.get("token"));
let token = localStorage.getItem("awo-token") || "";
const base = localStorage.getItem("awo-api") || "";

async function api(path, body) {
  const headers = token ? { "X-AWO-Token": token } : {};
  const res = await fetch(base + path, body ? { method: "POST", body: JSON.stringify(body), headers } : { headers });
  if (res.status === 401) {
    const given = prompt("This studio needs its access token:");
    if (given) {
      token = given;
      localStorage.setItem("awo-token", given);
      return api(path, body);
    }
  }
  return res.json();
}

async function load(folder) {
  state.flows = await api("/api/workflows");
  state.folder = folder || state.folder || (state.flows[0] && state.flows[0].folder);
  if (state.folder) {
    state.runs = await api(`/api/runs?w=${encodeURIComponent(state.folder)}`);
    state.yaml = (await api(`/api/yaml?w=${encodeURIComponent(state.folder)}`)).yaml || "";
  }
  draw();
}

const flow = () => state.flows.find((f) => f.folder === state.folder) || { nodes: [], files: [], problems: [] };

function drawRail() {
  $("wflist").innerHTML = state.flows.map((f) => `
    <li><button class="${f.folder === state.folder ? "is-on" : ""}" data-folder="${esc(f.folder)}">
      <span class="wfname">${esc(f.name)}</span>
      <span class="wfmeta">${f.nodes.length} nodes${f.schedule ? ` · cron ${f.schedule}` : f.alwaysOn ? ` · every ${f.interval}s` : ""}${f.problems.length ? ` · ${f.problems.length} warn` : ""}</span>
    </button></li>`).join("");
  $("wflist").querySelectorAll("button").forEach((b) =>
    b.onclick = () => load(b.dataset.folder));
  const files = flow().files;
  $("filelist").innerHTML = files.length
    ? files.map((f) => `<li>${esc(f)}</li>`).join("")
    : `<li class="empty">none yet</li>`;
  $("doccontrol").textContent = `${flow().name || "no workflow"} · ${state.runs.length} runs · ${
    base ? base.replace(/^https?:\/\//, "") : "local"}`;
}

function nodeStatus(name) {
  const last = state.runs[0];
  const hit = last && last.nodes.find((n) => n.name === name);
  if (!hit) return "";
  if (hit.skipped) return `<span class="node-status warn">skipped</span>`;
  if (hit.note) return `<span class="node-status warn">async</span>`;
  return `<span class="node-status ${hit.failed ? "err" : "ok"}">${hit.failed ? "failed" : "ok"} · ${hit.ms}ms</span>`;
}

function drawCanvas() {
  const nodes = flow().nodes;
  if (!nodes.length) return `<p class="empty">no nodes</p>`;
  return `<div class="canvas">${nodes.map((n, i) => {
    const kind = n.type || "agent";
    const rows = [];
    if (kind === "input") rows.push(["source", n.source || "text"], ["value", n.value || n.path || n.url || ""]);
    if (kind === "agent") {
      rows.push(["model", n.model || "—"], ["tools", (n.tools || []).join(", ") || "none"]);
      if (n.schema) rows.push(["schema", Object.keys(n.schema.properties || {}).join(", ") || "json"]);
      if (n.verify) rows.push(["verify", n.verify]);
      if (n.interval) rows.push(["every", `${n.interval}s`]);
    }
    if (kind === "agent") {
      if (n.map) rows.push(["map", `${n.parallel || 4} at a time`]);
      (n.mcp || []).forEach((m) => rows.push(["mcp", m.url]));
    }
    if (kind === "approval") rows.push(["prompt", n.prompt || "Approve this?"]);
    if (kind === "workflow") rows.push(["runs", n.ref || "—"]);
    if (kind === "output") {
      rows.push(["sink", n.sink || "print"], ["dedupe", n.dedupe || "off"]);
      if (n.wait) rows.push(["wait", `${n.wait}s`]);
      if (n.path) rows.push(["path", n.path]);
      if (n.url) rows.push(["url", n.url]);
    }
    if (n.when) rows.push(["when", n.when]);
    if (n.retry) rows.push(["retry", n.retry]);
    if (n.on_error) rows.push(["on error", n.on_error]);
    return `<div class="node is-${kind}">
        <div class="node-head"><span class="node-name">${esc(n.name || kind)}</span>
          ${nodeStatus(n.name)}
          <span class="node-kind">${kind} · ${n.mode || "sync"}</span></div>
        <div class="node-body">${rows.map(([k, v]) =>
      `<div class="node-row"><b>${esc(k)}</b><span>${esc(String(v)).slice(0, 180)}</span></div>`).join("")}</div>
      </div>${i < nodes.length - 1 ? `<div class="wire"></div><div class="wire-head"></div>` : ""}`;
  }).join("")}</div>`;
}

function records(run) {
  for (const node of [...(run.nodes || [])].reverse()) {
    try {
      const data = JSON.parse(node.output);
      for (const value of Object.values(data)) {
        if (Array.isArray(value) && value.length && typeof value[0] === "object") return value;
      }
    } catch (e) { /* not json, keep looking */ }
  }
  return [];
}

function spark(values) {
  if (values.length < 2) return "";
  const top = Math.max(...values) || 1;
  const points = values.map((v, i) =>
    `${(i / (values.length - 1)) * 100},${28 - (v / top) * 26}`).join(" ");
  return `<svg viewBox="0 0 100 28" preserveAspectRatio="none" style="width:70px;height:18px">
    <polyline points="${points}" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

function drawDashboard() {
  const last = state.runs[0];
  if (!last) return `<p class="empty">no runs yet, press Run cycle</p>`;
  const rows = records(last);
  const verified = rows.filter((r) => r.verified === true).length;
  const unverified = rows.filter((r) => r.verified === false).length;
  const failed = last.nodes.filter((n) => n.failed).length;
  const durations = state.runs.map((r) => r.ms || 0).reverse();
  const calls = last.nodes.flatMap((n) => (n.tool_calls || []).map((c) => ({ ...c, node: n.name })));

  const tile = (label, value, foot, cls = "") => `<div class="tile"><p class="eyebrow">${label}</p>
    <div class="tile-val ${cls}">${value}</div><div class="tile-foot">${foot || ""}</div></div>`;

  const keys = rows.length ? [...new Set(rows.flatMap((r) => Object.keys(r)))].slice(0, 7) : [];

  return `<div class="tiles">
      ${tile("Last run", failed ? "FAILED" : "OK", esc(last.started), failed ? "err" : "ok")}
      ${tile("Duration", `${last.ms}ms`, spark(durations) + " last " + durations.length)}
      ${tile("Records", rows.length, `${last.nodes.length} nodes`)}
      ${tile("Verified", verified, unverified ? `${unverified} unverified` : "all backed by a page", unverified ? "warn" : "ok")}
    </div>
    <div class="widget"><h3>Records</h3>${rows.length ? `<table><thead><tr>${keys.map((k) =>
    `<th>${esc(k)}</th>`).join("")}</tr></thead><tbody>${rows.slice(0, 40).map((r) =>
      `<tr>${keys.map((k) => {
        const v = r[k];
        const cell = typeof v === "string" && v.startsWith("http")
          ? `<a href="${esc(v)}" target="_blank" rel="noreferrer">${esc(v).slice(0, 48)}</a>`
          : esc(typeof v === "object" ? JSON.stringify(v) : v).slice(0, 120);
        return `<td class="${k === "verified" ? (v ? "mono ok" : "mono err") : "mono"}">${cell}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table>`
      : `<p class="empty">last run produced no JSON records</p>`}</div>
    <div class="widget"><h3>Tool calls</h3>${calls.length ? `<div class="log">${calls.map((c) =>
        `<span class="k">${esc(c.node)} → ${esc(c.tool)}</span>(${esc(JSON.stringify(c.args))})\n${esc(c.result).slice(0, 300)}`).join("\n\n")}</div>`
      : `<p class="empty">no tools were called</p>`}</div>
    <div class="widget"><h3>Node outputs</h3><table><thead><tr><th>Node</th><th>Ms</th><th>Output</th></tr></thead><tbody>
      ${last.nodes.map((n) => `<tr><td class="mono">${esc(n.name)}</td><td class="mono">${n.ms == null ? "—" : n.ms}</td>
        <td class="mono">${esc(n.note || n.output || "").slice(0, 400)}</td></tr>`).join("")}</tbody></table></div>`;
}

function drawSource() {
  const problems = flow().problems;
  return `${problems.length ? `<div class="widget"><h3>Warnings</h3>${problems.map((p) =>
    `<p class="bullet">${esc(p)}</p>`).join("")}</div>` : ""}
    <div class="widget"><h3>workflow.yaml</h3><div class="log">${esc(state.yaml)}</div></div>`;
}

function bar(series, unit) {
  if (!series.length) return `<p class="empty">no runs yet</p>`;
  const top = Math.max(...series.map((p) => p.value)) || 1;
  return `<div class="bars">${series.map((p) =>
    `<span style="height:${Math.max(2, (p.value / top) * 70)}px" title="${esc(p.label)}: ${p.value}${unit}"></span>`).join("")}</div>
    <div class="barlabels">${series.map((p) => `<span>${esc(p.label)}</span>`).join("")}</div>`;
}

function widgetBody(w) {
  const d = w.data || {};
  if (d.error) return `<p class="empty">${esc(d.error)}</p>`;
  if (d.empty) return `<p class="empty">${esc(d.empty)}</p>`;
  if (d.tiles) return d.tiles.map((t) =>
    `<div style="margin-bottom:8px"><p class="eyebrow">${esc(t.label)}</p>
      <div class="bw-val">${esc(t.value)}</div>
      <div class="bw-foot">${esc(t.foot)}</div></div>`).join("");
  if (d.series) return bar(d.series, d.unit || "");
  if (d.columns) return `<table><thead><tr>${d.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${d.rows.map((r) => `<tr>${r.map((v) =>
      `<td class="mono">${esc(typeof v === "object" ? JSON.stringify(v) : v).slice(0, 80)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  if (d.items) return `<ul class="mini">${d.items.map((i) => `<li>${esc(i).slice(0, 120)}</li>`).join("")}</ul>`;
  if (d.lines) return `<div class="log">${d.lines.map((l) => esc(l)).join("\n\n")}</div>`;
  if (d.value !== undefined) return `<div class="bw-val ${d.state || ""}">${esc(d.value)}</div>
    <div class="bw-foot">${esc(d.foot || "")}${d.spark ? spark(d.spark) : ""}</div>`;
  return `<p class="empty">nothing to show</p>`;
}

function drawBoard() {
  const widgets = (state.board && state.board.widgets) || [];
  const editor = state.adding ? `<form class="editor" id="widgetform">
      <label>Title<input id="w-title" value="New widget"></label>
      <label>Kind<select id="w-kind">
        ${["stat", "table", "list", "chart", "log", "machine"].map((k) => `<option>${k}</option>`).join("")}</select></label>
      <label>Workflow<select id="w-flow">${state.flows.map((f) =>
    `<option value="${esc(f.folder)}">${esc(f.name)}</option>`).join("")}</select></label>
      <label>Metric<select id="w-metric">
        ${["records", "verified", "duration_ms", "status", "runs"].map((m) => `<option>${m}</option>`).join("")}</select></label>
      <label>Field<input id="w-field" placeholder="e.g. title"></label>
      <button class="btn primary" type="submit">Add</button>
    </form>` : "";
  return `${editor}<div class="board">${widgets.length ? widgets.map((w) => `
      <div class="bw ${["table", "log", "chart"].includes(w.kind) ? "wide" : ""}">
        <div class="bw-head"><p class="eyebrow">${esc(w.title || w.kind)}</p>
          <button class="bw-drop" data-drop="${esc(w.id)}">remove</button></div>
        ${widgetBody(w)}
        <div class="bw-src">${esc(w.kind)}${w.workflow ? ` · ${esc(w.workflow)}` : ""}</div>
      </div>`).join("") : `<p class="empty">no widgets yet, press Add widget</p>`}</div>`;
}

function draw() {
  drawRail();
  $("stage").innerHTML = state.view === "board" ? drawBoard()
    : state.view === "canvas" ? drawCanvas()
      : state.view === "dashboard" ? drawDashboard() : drawSource();
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("is-on", t.dataset.view === state.view));
  $("addwidget").style.display = state.view === "board" ? "" : "none";
  $("boardbtn").classList.toggle("is-on", state.view === "board");
  $("stage").querySelectorAll("[data-drop]").forEach((b) => b.onclick = async () => {
    state.board.widgets = state.board.widgets.filter((w) => w.id !== b.dataset.drop);
    await api("/api/board", { widgets: state.board.widgets });
    loadBoard();
  });
  const form = $("widgetform");
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    const widget = { id: `w${Date.now()}`, title: $("w-title").value, kind: $("w-kind").value };
    if (widget.kind !== "machine") {
      widget.workflow = $("w-flow").value;
      if (["stat", "chart"].includes(widget.kind)) widget.metric = $("w-metric").value;
      if ($("w-field").value) widget.field = $("w-field").value;
    }
    const saved = (state.board.widgets || []).concat(widget);
    await api("/api/board", { widgets: saved });
    state.adding = false;
    loadBoard();
  };
}

async function loadBoard() {
  state.board = await api("/api/board/data");
  state.view = "board";
  if (!state.flows.length) state.flows = await api("/api/workflows");
  draw();
  $("boardmeta").textContent = `${(state.board.widgets || []).length} widgets`;
}

function say(who, text) {
  $("chatlog").insertAdjacentHTML("beforeend",
    `<div class="msg ${who === "you" ? "me" : "awo"}"><span class="who">${who}</span>${esc(text)}</div>`);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}

document.querySelectorAll(".tab").forEach((t) =>
  t.onclick = () => { state.view = t.dataset.view; draw(); });
$("refresh").onclick = () => (state.view === "board" ? loadBoard() : load());
$("boardbtn").onclick = () => loadBoard();
$("addwidget").onclick = () => { state.adding = !state.adding; draw(); };
$("run").onclick = async () => {
  if (!state.folder) return;
  $("run").disabled = true;
  $("run").textContent = "Running…";
  const out = await api("/api/run", { folder: state.folder });
  $("run").disabled = false;
  $("run").textContent = "Run cycle";
  if (!out.success) say("awo", `run failed: ${out.error}`);
  state.view = "dashboard";
  load();
};
$("chatform").onsubmit = async (e) => {
  e.preventDefault();
  const message = $("chatinput").value.trim();
  if (!message) return;
  say("you", message);
  $("chatinput").value = "";
  say("awo", "building, this takes a minute on a local model …");
  const editing = $("editmode").checked && state.folder;
  const out = await api("/api/chat", { message, folder: editing ? state.folder : null });
  $("chatlog").lastElementChild.remove();
  if (out.success) {
    say("awo", `${editing ? "edited" : "created"} ${out.folder}${out.warnings && out.warnings.length ? ` · ${out.warnings.length} warning(s)` : ""}`);
    state.view = "canvas";
    load(out.folder);
  } else {
    say("awo", `failed: ${out.error}`);
  }
};
load();
