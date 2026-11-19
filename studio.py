"""AWO Studio: nodes on a canvas, dashboards from run records, chat to build workflows.

Local:  .venv/bin/python studio.py                    then open http://127.0.0.1:8740
Remote: AWO_TOKEN=<secret> .venv/bin/python studio.py 8740 --host 0.0.0.0
        and open http://<that machine>:8740 from anywhere, pasting the same token.

Binding past loopback without a token is refused: the API can run shell commands.
"""
import hmac
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src", "engine"))

import yaml  # noqa: E402

import compute  # noqa: E402
import diffs  # noqa: E402
import editing  # noqa: E402
import events  # noqa: E402
import metrics as metricstore  # noqa: E402
import runner  # noqa: E402
from workflow import Workflow, validate  # noqa: E402
from workflow_creation import (WORKFLOWS_DIR, answer_question, create_workflow_from_ai,  # noqa: E402
                               edit_workflow_from_ai, propose_edit, propose_workflow)

UI = os.path.join(ROOT, "ui")
DIST = os.path.join(UI, "dist")
LEGACY = os.path.join(UI, "legacy")
RUNNER = runner.Runner(WORKFLOWS_DIR)
BOARD = os.path.join(ROOT, "board.json")
TOKEN = os.environ.get("AWO_TOKEN", "")
PUBLIC = {"/api/health"}
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
         ".woff2": "font/woff2", ".svg": "image/svg+xml"}


def folders():
    return sorted(d for d in os.listdir(WORKFLOWS_DIR)
                  if os.path.isfile(os.path.join(WORKFLOWS_DIR, d, "workflow.yaml")))


def describe(folder):
    path = os.path.join(WORKFLOWS_DIR, folder)
    data = yaml.safe_load(open(os.path.join(path, "workflow.yaml"), "r")) or {}
    active = RUNNER.active(folder)
    return {"folder": folder, "name": data.get("name", folder), "purpose": data.get("purpose", ""),
            "alwaysOn": bool(data.get("alwaysOn")), "interval": data.get("interval", 300),
            "schedule": data.get("schedule"), "metrics": data.get("metrics") or [],
            "nodes": data.get("nodes") or data.get("agents", []), "problems": validate(data),
            "running": active.run_id if active else None,
            "files": [f for f in sorted(os.listdir(path))
                      if f not in ("workflow.yaml", "runs", "versions")]}


def ui_root():
    """The built app when it exists, otherwise the pre-React page, so the studio is never blank."""
    return DIST if os.path.isfile(os.path.join(DIST, "index.html")) else LEGACY


def runs(folder, limit=24):
    root = os.path.join(WORKFLOWS_DIR, folder, "runs")
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root))[-limit:][::-1]:
        try:
            with open(os.path.join(root, name, "run.json"), "r") as f:
                out.append(json.load(f))
        except Exception:
            pass
    return out


def board():
    try:
        with open(BOARD, "r") as f:
            return json.load(f)
    except Exception:
        return {"widgets": []}


def save_board(data):
    with open(BOARD, "w") as f:
        json.dump(data, f, indent=2)
    return data


def records_in(run):
    """The first array of records any node in this run produced."""
    for node in reversed(run.get("nodes", [])):
        try:
            payload = json.loads(node.get("output") or "")
        except Exception:
            continue
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload
        if isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return value
    return []


def resolve(widget):
    """Turn one widget definition into the numbers or rows the page should draw."""
    kind = widget.get("kind", "stat")
    if kind == "machine":
        state = compute.snapshot()
        return {"tiles": [
            {"label": "cpu", "value": f"{state['cpu_percent']}%", "foot": f"load {state['load']} on {state['cores']} cores"},
            {"label": "free ram", "value": f"{state['free_ram_gb']}GB" if state["free_ram_gb"] is not None else "—", "foot": ""},
            {"label": "gpu", "value": f"{state['gpu_percent']}%" if state["gpu_percent"] is not None else "—",
             "foot": f"{state['gpu_free_gb']}GB free" if state["gpu_free_gb"] is not None else "no reading"},
        ]}
    folder = widget.get("workflow")
    if not folder or not os.path.isdir(os.path.join(WORKFLOWS_DIR, folder)):
        return {"error": f"no workflow called {folder}"}
    history = runs(folder, int(widget.get("limit", 24)))
    if not history:
        return {"empty": "this workflow has not run yet"}
    last = history[0]
    rows = records_in(last)
    if kind == "stat":
        metric = widget.get("metric", "records")
        if metric == "records":
            return {"value": len(rows), "foot": f"last run {last['started']}"}
        if metric == "verified":
            good = sum(1 for r in rows if r.get("verified") is True)
            return {"value": good, "foot": f"{len(rows) - good} unverified", "state": "ok" if good == len(rows) else "warn"}
        if metric == "duration_ms":
            return {"value": f"{last.get('ms', 0)}ms", "foot": f"over {len(history)} runs",
                    "spark": [r.get("ms", 0) for r in reversed(history)]}
        if metric == "status":
            failed = [n for n in last.get("nodes", []) if n.get("failed")]
            return {"value": "FAILED" if failed else "OK", "state": "err" if failed else "ok",
                    "foot": last["started"]}
        if metric == "runs":
            return {"value": len(history), "foot": f"since {history[-1]['started']}"}
        field = widget.get("field")
        if field and rows:
            numbers = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
            if numbers:
                how = widget.get("agg", "sum")
                value = {"avg": sum(numbers) / len(numbers), "min": min(numbers), "max": max(numbers),
                         "count": len(numbers)}.get(how, sum(numbers))
                return {"value": round(value, 2),
                        "foot": f"{how} of {field} over {len(numbers)} records"}
        return {"error": f"unknown metric {metric}"}
    if kind == "table":
        keys = widget.get("columns") or (sorted({k for r in rows for k in r})[:7] if rows else [])
        return {"columns": keys, "rows": [[r.get(k) for k in keys] for r in rows[:40]]}
    if kind == "list":
        field = widget.get("field") or "title"
        return {"items": [str(r.get(field, "")) for r in rows[:40] if r.get(field) is not None]}
    if kind == "chart":
        metric = widget.get("metric", "duration_ms")
        series = [{"label": r["started"][11:16],
                   "value": r.get("ms", 0) if metric == "duration_ms" else len(records_in(r))}
                  for r in reversed(history)]
        return {"series": series, "unit": "ms" if metric == "duration_ms" else "records"}
    if kind == "log":
        calls = [f"{n.get('name')} -> {c['tool']}({json.dumps(c['args'])})\n{c['result'][:200]}"
                 for n in last.get("nodes", []) for c in n.get("tool_calls", [])]
        return {"lines": calls[:20]}
    return {"error": f"unknown widget kind {kind}"}


class Studio(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _allowed(self, path):
        """A token is needed for everything but the health check and the page itself."""
        if not TOKEN or path in PUBLIC or not path.startswith("/api/"):
            return True
        given = self.headers.get("X-AWO-Token") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return hmac.compare_digest(given, TOKEN)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "X-AWO-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send(self, body, ctype="application/json", code=200):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _stream(self, folder, after, run_id=None):
        """Server-sent events: replay one run's missed lines, then follow the bus live.

        Only the run the browser names is replayed. Replaying every past run would hand a
        fresh page a pile of finished runs and let it paint one of them as the live one.
        """
        box = events.BUS.subscribe()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def write(line):
            self.wfile.write(f"id: {line.get('seq', 0)}\ndata: {json.dumps(line)}\n\n".encode())
            self.wfile.flush()

        try:
            for line in (events.BUS.history(run_id, after) if run_id else []):
                if folder and line.get("workflow") != folder:
                    continue
                write(line)
            while True:
                try:
                    line = box.get(timeout=15)
                except Exception:
                    write({"type": "heartbeat", "run_id": "", "seq": 0, "at": time.time()})
                    continue
                if folder and line.get("workflow") != folder:
                    continue
                write(line)
        except Exception:
            pass  # the browser went away
        finally:
            events.BUS.drop(box)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/api/health":
            return self._send({"ok": True, "needs_token": bool(TOKEN), "compute": compute.snapshot()})
        if not self._allowed(url.path):
            return self._send({"error": "bad or missing token"}, code=401)
        if url.path == "/api/workflows":
            return self._send([describe(f) for f in folders()])
        if url.path == "/api/runs":
            return self._send(runs(query["w"][0], int(query.get("limit", ["24"])[0])))
        if url.path == "/api/board":
            return self._send(board())
        if url.path == "/api/board/data":
            config = board()
            return self._send({"widgets": [dict(w, data=resolve(w)) for w in config.get("widgets", [])]})
        if url.path == "/api/compute":
            return self._send(compute.snapshot())
        if url.path == "/api/yaml":
            with open(os.path.join(WORKFLOWS_DIR, query["w"][0], "workflow.yaml"), "r") as f:
                return self._send({"yaml": f.read()})
        if url.path == "/api/events":
            return self._stream((query.get("w") or [None])[0],
                                int((query.get("after") or ["0"])[0]),
                                (query.get("run") or [None])[0])
        if url.path.startswith("/api/run/"):
            run = RUNNER.get(url.path.rsplit("/", 1)[1])
            if not run:
                return self._send({"error": "no such run"}, code=404)
            return self._send({"run": run.model_dump(),
                               "events": events.BUS.history(run.run_id)})
        if url.path == "/api/active":
            folder = (query.get("w") or [None])[0]
            run = RUNNER.active(folder) if folder else None
            return self._send({"run": run.model_dump() if run else None,
                               "recent": [r.model_dump() for r in RUNNER.recent(folder, 10)]})
        if url.path == "/api/metrics":
            folder = query["w"][0]
            window = (query.get("range") or ["7d"])[0]
            path = os.path.join(WORKFLOWS_DIR, folder)
            data = yaml.safe_load(open(os.path.join(path, "workflow.yaml"), "r")) or {}
            return self._send({"declared": data.get("metrics") or [], "range": window,
                               "lines": metricstore.read(path, metricstore.since_for(window))})
        if url.path == "/api/metrics/system":
            window = (query.get("range") or ["7d"])[0]
            return self._send(metricstore.system([os.path.join(WORKFLOWS_DIR, f) for f in folders()],
                                                 window) | {"range": window})
        if url.path == "/api/versions":
            return self._send({"versions": editing.versions(os.path.join(WORKFLOWS_DIR, query["w"][0]))})

        root = ui_root()
        name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
        path = os.path.normpath(os.path.join(root, name))
        if not path.startswith(root) or not os.path.isfile(path):
            if url.path.startswith("/api/") or "." in os.path.basename(url.path):
                return self._send({"error": "not found"}, code=404)
            path = os.path.join(root, "index.html")  # the app owns its own routes
            if not os.path.isfile(path):
                return self._send({"error": "no ui built, run: cd ui && npm run build"}, code=404)
        with open(path, "rb") as f:
            self._send(f.read(), TYPES.get(os.path.splitext(path)[1], "text/plain"))

    def do_POST(self):
        url = urlparse(self.path)
        if not self._allowed(url.path):
            return self._send({"error": "bad or missing token"}, code=401)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if url.path == "/api/run":
            # a run now happens in its own thread and is watched over /api/events
            state, problem = RUNNER.start(body["folder"], mode=body.get("mode", "run"),
                                          from_node=body.get("from_node"), seed=body.get("input"))
            if problem:
                return self._send({"success": False, "error": problem})
            return self._send({"success": True, "run": state.model_dump()})
        if url.path == "/api/control":
            state, problem = RUNNER.control(body.get("run_id", ""), body.get("action", ""))
            if problem:
                return self._send({"success": False, "error": problem})
            return self._send({"success": True, "run": state.model_dump()})
        if url.path == "/api/apply":
            folder = os.path.join(WORKFLOWS_DIR, body["folder"])
            return self._send(editing.apply_yaml(folder, body.get("yaml", ""),
                                                 label=body.get("label", "chat")))
        if url.path == "/api/ask":
            folder = os.path.join(WORKFLOWS_DIR, body["folder"])
            history = runs(body["folder"], 1)
            summary = ""
            if history:
                last = history[0]
                lines = [f"run {last.get('run_id', '')} {last.get('status', '')} in {last.get('ms', 0)}ms"]
                for node in last.get("nodes", []):
                    verdict = node.get("validation") or {}
                    lines.append(
                        f"- {node.get('name')} ({node.get('type')}): {node.get('status', '')}"
                        f"{' FAILED: ' + str(node.get('error'))[:400] if node.get('failed') else ''}"
                        f"{' problems: ' + '; '.join(verdict.get('problems', [])) if verdict.get('problems') else ''}"
                        f" output: {str(node.get('output'))[:400]}")
                summary = "\n".join(lines)
            return self._send(answer_question(folder, body.get("question", ""), summary))
        if url.path == "/api/create":
            return self._send(editing.create_from_yaml(WORKFLOWS_DIR, body.get("yaml", "")))
        if url.path == "/api/restore":
            folder = os.path.join(WORKFLOWS_DIR, body["folder"])
            return self._send(editing.restore(folder, body.get("version", "")))
        if url.path == "/api/node":
            folder = os.path.join(WORKFLOWS_DIR, body["folder"])
            return self._send(editing.node_action(folder, body.get("action", ""), body.get("name", ""),
                                                  x=body.get("x", 0), y=body.get("y", 0)))
        if url.path == "/api/board/pin":
            board_now = board()
            widgets = [w for w in board_now.get("widgets", []) if w.get("id") != body["widget"].get("id")]
            return self._send(save_board({"widgets": widgets + [body["widget"]]}))
        if url.path.startswith("/api/trigger/"):  # webhook trigger: POST to run one cycle
            folder = url.path.rsplit("/", 1)[-1]
            try:
                Workflow(os.path.join(WORKFLOWS_DIR, folder)).run_once()
                return self._send({"success": True, "runs": runs(folder, 1)})
            except Exception as e:
                return self._send({"success": False, "error": str(e)})
        if url.path == "/api/board":
            return self._send(save_board({"widgets": body.get("widgets", [])}))
        if url.path == "/api/chat":
            # propose: write nothing, hand back the yaml and a structural diff for the canvas
            if body.get("propose"):
                if body.get("folder"):
                    folder = os.path.join(WORKFLOWS_DIR, body["folder"])
                    result = propose_edit(folder, body["message"], node=body.get("node", ""))
                    if result.get("success"):
                        result["diff"] = diffs.diff(result.get("current", ""), result["yaml"])
                        result["folder"] = body["folder"]
                else:
                    result = propose_workflow(body["message"])
                    if result.get("success"):
                        result["diff"] = diffs.diff("", result["yaml"])
                return self._send(result)
            if body.get("folder"):
                result = edit_workflow_from_ai(os.path.join(WORKFLOWS_DIR, body["folder"]), body["message"])
            else:
                result = create_workflow_from_ai(body["message"])
            if result.get("success"):
                result["folder"] = os.path.basename(os.path.dirname(result["filepath"]))
            return self._send(result)
        self._send({"error": "not found"}, code=404)


def serve(port=8740, host="127.0.0.1", token=""):
    """Serve the studio until ctrl-c, then release the port so a caller can keep going."""
    global TOKEN
    if token:
        TOKEN = token
    if host not in ("127.0.0.1", "localhost", "::1") and not TOKEN:
        TOKEN = secrets.token_urlsafe(24)
        print(f"listening past this machine, so a token is required. Generated one:\n\n    {TOKEN}\n\n"
              f"Set AWO_TOKEN to keep the same one across restarts.")
    httpd = ThreadingHTTPServer((host, port), Studio)
    print(f"studio on http://{host}:{port}" + ("  (token required)" if TOKEN else ""))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    args = sys.argv[1:]
    serve(port=int(args[0]) if args and args[0].isdigit() else 8740,
          host=args[args.index("--host") + 1] if "--host" in args else "127.0.0.1",
          token=args[args.index("--token") + 1] if "--token" in args else "")
