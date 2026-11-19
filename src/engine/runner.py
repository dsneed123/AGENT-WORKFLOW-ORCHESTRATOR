"""The studio's view of runs: start one, watch it, pause it, stop it, retry one node.

A run lives in its own thread. Its state is rebuilt from the same events the studio streams,
so the server and the browser never hold two different stories about what happened.
"""
import os
import threading
import time
import traceback
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

import events
from workflow import Workflow

KEEP = 60  # runs held in memory


class Control:
    """Pause finishes the node that is running, then holds. Stop cancels what is left."""

    def __init__(self):
        self._resume = threading.Event()
        self._resume.set()
        self._stop = threading.Event()
        self.paused = False

    def pause(self):
        self.paused = True
        self._resume.clear()

    def resume(self):
        self.paused = False
        self._resume.set()

    def stop(self):
        self._stop.set()
        self._resume.set()

    @property
    def stopped(self):
        return self._stop.is_set()

    def gate(self):
        """Called between nodes: holds while paused, and says so when the run was stopped."""
        if self._stop.is_set():
            return "stopped"
        if not self._resume.is_set():
            self._resume.wait()
        return "stopped" if self._stop.is_set() else None


class NodeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = "agent"
    mode: str = "sync"
    status: str = "pending"      # pending | running | success | failed | skipped | cancelled
    ms: Optional[int] = None
    tokens: dict[str, int] = Field(default_factory=dict)
    model: str = ""
    input: str = ""
    output: str = ""
    error: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    validation: Optional[dict[str, Any]] = None
    disabled: bool = False


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    workflow: str = ""           # folder
    name: str = ""
    mode: str = "run"            # run | test
    status: str = "idle"         # idle | running | paused | failed | completed | stopped
    from_node: str = ""
    started: float = 0
    finished: Optional[float] = None
    ms: Optional[int] = None
    tokens: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    seq: int = 0
    nodes: list[NodeState] = Field(default_factory=list)

    def node(self, name):
        return next((n for n in self.nodes if n.name == name), None)

    def apply(self, line):
        """Fold one event into this run's state. The browser store does exactly the same."""
        kind = line["type"]
        self.seq = max(self.seq, line.get("seq", 0))
        name = line.get("node") or ""
        if kind == "run_started":
            self.mode = line.get("mode") or self.mode
            self.from_node = line.get("from_node") or ""
            self.status = "running"
            self.started = line.get("at") or time.time()
            self.nodes = [NodeState(name=n.get("name", ""), type=n.get("type", "agent"),
                                    mode=n.get("mode", "sync"), disabled=bool(n.get("disabled")),
                                    status="pending") for n in line.get("nodes", [])]
        elif kind == "node_started":
            node = self.node(name)
            if node:
                node.status = "running"
                node.input = line.get("text") or ""
        elif kind == "node_output":
            node = self.node(name)
            if node:
                node.output = line.get("text") or ""
        elif kind == "tool_call":
            node = self.node(name)
            if node:
                node.tool_calls.append({"tool": line.get("tool"), "args": line.get("args"),
                                        "result": line.get("result"), "ms": line.get("ms")})
        elif kind == "node_completed":
            node = self.node(name)
            if node:
                node.status = line.get("status") or "success"
                node.ms = line.get("ms")
                node.tokens = line.get("tokens") or {}
                node.model = line.get("model") or ""
                node.validation = line.get("validation")
        elif kind == "node_failed":
            node = self.node(name)
            if node:
                node.status = "failed"
                node.ms = line.get("ms")
                node.error = line.get("error") or ""
        elif kind == "run_paused":
            self.status = "paused"
        elif kind == "run_resumed":
            self.status = "running"
        elif kind == "run_stopped":
            self.status = "stopped"
        elif kind == "run_completed":
            self.status = line.get("status") or "completed"
            self.ms = line.get("ms")
            self.tokens = line.get("tokens") or {}
            self.metrics = line.get("metrics") or {}
            self.error = line.get("error") or ""
            self.finished = line.get("at") or time.time()
        return self


class Runner:
    def __init__(self, workflows_dir):
        self.root = workflows_dir
        self.runs = {}
        self.controls = {}
        self.threads = {}
        self.lock = threading.Lock()
        self.box = events.BUS.subscribe()
        threading.Thread(target=self._follow, daemon=True).start()

    def _follow(self):
        """Keep every run's state in step with the stream the studio is watching."""
        while True:
            line = self.box.get()
            with self.lock:
                run = self.runs.get(line["run_id"])
                if run:
                    run.apply(line)

    def start(self, folder, mode="run", from_node=None, seed=None):
        path = os.path.join(self.root, folder)
        if not os.path.isfile(os.path.join(path, "workflow.yaml")):
            return None, f"no workflow called {folder}"
        with self.lock:
            busy = next((r for r in self.runs.values()
                         if r.workflow == folder and r.status in ("running", "paused")), None)
            if busy:
                return None, f"{folder} is already running as {busy.run_id}"
            run_id = f"{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"
            state = RunState(run_id=run_id, workflow=folder, mode=mode,
                             from_node=from_node or "", status="running", started=time.time())
            self.runs[run_id] = state
            self.controls[run_id] = Control()
            for old in sorted(self.runs, key=lambda r: self.runs[r].started)[:-KEEP]:
                self.runs.pop(old, None)
                self.controls.pop(old, None)
        thread = threading.Thread(target=self._run, daemon=True,
                                  args=(run_id, path, mode, from_node, seed))
        thread.start()
        self.threads[run_id] = thread
        return state, None

    def _run(self, run_id, path, mode, from_node, seed):
        try:
            flow = Workflow(path)
            with self.lock:
                if run_id in self.runs:
                    self.runs[run_id].name = flow.name
            flow.run_once(run_id=run_id, mode=mode, from_node=from_node, seed=seed,
                          control=self.controls.get(run_id))
        except Exception as e:
            traceback.print_exc()
            events.BUS.publish(type="run_completed", run_id=run_id,
                               workflow=os.path.basename(path), status="failed", error=str(e)[:500])

    def control(self, run_id, action):
        control = self.controls.get(run_id)
        run = self.runs.get(run_id)
        if not control or not run:
            return None, f"no run called {run_id}"
        if run.status not in ("running", "paused"):
            return None, f"{run_id} is {run.status}, nothing to {action}"
        if action == "pause":
            control.pause()
            events.BUS.publish(type="run_paused", run_id=run_id, workflow=run.workflow)
        elif action == "resume":
            control.resume()
            events.BUS.publish(type="run_resumed", run_id=run_id, workflow=run.workflow)
        elif action == "stop":
            control.stop()
        else:
            return None, f"unknown action {action}"
        return run, None

    def get(self, run_id):
        return self.runs.get(run_id)

    def recent(self, folder=None, limit=20):
        runs = [r for r in self.runs.values() if folder is None or r.workflow == folder]
        return sorted(runs, key=lambda r: -r.started)[:limit]

    def active(self, folder):
        return next((r for r in self.recent(folder) if r.status in ("running", "paused")), None)
