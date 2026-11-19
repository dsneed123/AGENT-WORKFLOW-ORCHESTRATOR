import concurrent.futures
import csv
import datetime
import json
import os
import queue
import sqlite3
import sys
import re
import shutil
import textwrap
import threading
import time

import httpx
import yaml

from agent import BY_NAME, Agent
import checks
import compute
import events
import mcp
import memory
import metrics
import sandbox
import research
from models import Node, NodeRecord, Payload, RunRecord, WorkflowSpec, records_in

OR, GR, O = "\033[38;5;166m", "\033[38;5;245m", "\033[0m"
MAX_LINES = 20


def box(title, tag, text):
    width = min(shutil.get_terminal_size((100, 24)).columns, 100)
    inner = width - 4
    head = f"┌─ {title} "
    tail = f" {tag} ┐"
    print(f"{OR}{head}{'─' * max(1, width - len(head) - len(tail))}{tail}{O}")
    lines = []
    for para in ((text or "").strip() or "(empty)").splitlines():
        lines += textwrap.wrap(para, inner) or [""]
    for line in lines[:MAX_LINES]:
        print(f"{OR}│{O} {line:<{inner}} {OR}│{O}")
    if len(lines) > MAX_LINES:
        more = f"... {len(lines) - MAX_LINES} more lines"
        print(f"{OR}│{O} {more:<{inner}} {OR}│{O}")
    print(f"{OR}└{'─' * (width - 2)}┘{O}")


def link():
    print(f"{OR}   │{O}")
    print(f"{OR}   ▼{O}")


def run_input(node):
    node = Node.of(node)
    source = node.source
    try:
        if source == "text":
            return str(node.value)
        if source == "file":
            with open(node.path, "r") as f:
                return f.read()
        if source == "api":
            return httpx.request(node.method, node.url, timeout=30,
                                 headers=node.headers or {}, json=node.body,
                                 follow_redirects=True).text
        if source == "mcp":
            return mcp.call(node.url, node.tool, node.arguments or {})
        return f"error: unknown input source '{source}'"
    except Exception as e:
        return f"error {e}"


SMART = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
                       "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
                       "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ", "\u2026": "..."})


def _flat(quote):
    """One spelling for both sides of a quote check: pages use curly quotes, models type straight ones."""
    flat = re.sub(r"\s+", " ", (quote or "").translate(SMART).lower()).strip()
    return flat.strip("\"' ")


def check_record(record):
    """Decide whether one record is backed by a page this workflow really read."""
    link = next((v for v in record.values() if isinstance(v, str) and v.startswith("http")), None)
    if not link:
        return False, "no link"
    page = research.fetched_text(link)
    if page is None:
        if research.key(link) in research.state()["offered"]:
            return False, "link came from search but was never opened"
        return False, "link was never visited"
    quote = next((record[f] for f in ("quote", "evidence_quote", "snippet") if record.get(f)), None)
    if quote is None:
        return False, "no quote to check against the page"
    if len(_flat(quote)) < 15:
        return False, "quote too short to prove anything"
    if _flat(quote) not in _flat(page):
        return False, "quote is not on that page"
    return True, "quote found on the page that was read"


def verify_records(text, strict=False):
    """Stamp every record in the JSON with whether its link and quote hold up. Strict drops the failures."""
    try:
        data = json.loads(text)
    except Exception:
        return text
    passed, failed = [0], [0]

    def walk(node):
        if isinstance(node, dict):
            if any(isinstance(v, str) and v.startswith("http") for v in node.values()):
                ok, why = check_record(node)
                node["verified"], node["evidence"] = ok, why
                (passed if ok else failed)[0] += 1
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for index in reversed(range(len(node))):
                walk(node[index])
                item = node[index]
                if strict and isinstance(item, dict) and item.get("verified") is False:
                    node.pop(index)

    walk(data)
    if failed[0]:
        word = "dropped" if strict else "marked unverified"
        print(f"{GR}{passed[0]} record(s) backed by a page that was read, {failed[0]} {word}{O}")
    return json.dumps(data, indent=2)


ENV = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")
SECRETS = set()  # every real secret value this process has substituted, so none is ever written down


def _secret(match):
    value = os.environ.get(match.group(1), "")
    if value:
        SECRETS.add(value)
    return value


def redact(text):
    """Blank out any secret before it reaches a run record, a log line or the studio."""
    out = str(text)
    for value in SECRETS:
        out = out.replace(value, "***")
    return out


def expand(value):
    """Swap ${env:NAME} for the real secret, so keys live in the environment and not in the yaml."""
    if isinstance(value, str):
        return ENV.sub(_secret, value)
    if isinstance(value, dict):
        return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v) for v in value]
    return value


rows_of = records_in  # the first array of records inside a JSON payload


def send_output(node, text, folder):
    """Put the result somewhere other than the terminal."""
    node = Node.of(node)
    sink = node.sink
    if sink == "print":
        return text
    if sandbox.dry_run():
        print(f"{GR}{sandbox.mocked(f'send {len(records_in(text)) or 1} item(s) to {sink}')}{O}")
        return text
    rows = records_in(text)
    default = {"file": "output.jsonl", "csv": "output.csv", "sqlite": "output.db"}.get(sink, "output.jsonl")
    path = os.path.join(folder, node.path or default)
    try:
        if sink == "file":
            with open(path, "a") as f:
                f.write(text.strip() + "\n")
        elif sink == "csv":
            if not rows:
                return text
            keys = sorted({k for row in rows for k in row})
            fresh = not os.path.exists(path)
            with open(path, "a", newline="") as f:
                writer = csv.DictWriter(f, keys)
                if fresh:
                    writer.writeheader()
                for row in rows:
                    writer.writerow({k: json.dumps(row[k]) if isinstance(row.get(k), (dict, list)) else row.get(k)
                                     for k in keys})
        elif sink == "sqlite":
            if not rows:
                return text
            keys = sorted({k for row in rows for k in row})
            table = re.sub(r"\W", "_", node.table)
            db = sqlite3.connect(path)
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(f'\"{k}\" TEXT' for k in keys)})")
            existing = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            for k in keys:
                if k not in existing:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN "{k}" TEXT')
            db.executemany(
                f"INSERT INTO {table} ({', '.join(chr(34) + k + chr(34) for k in keys)}) "
                f"VALUES ({', '.join('?' * len(keys))})",
                [[json.dumps(r[k]) if isinstance(r.get(k), (dict, list)) else r.get(k) for k in keys] for r in rows])
            db.commit()
            db.close()
        elif sink in ("webhook", "slack"):
            url = node.url or ""
            if not url:
                return f"error: {sink} sink has no url"
            body = {"text": text[:3000]} if sink == "slack" else (json.loads(text) if text.strip().startswith(("{", "[")) else {"text": text})
            httpx.post(url, json=body, timeout=20).raise_for_status()
        else:
            return f"error: unknown sink '{sink}'"
        print(f"{GR}{node.name} sent {len(rows) or 1} item(s) to {sink}{O}")
    except Exception as e:
        return f"error sending to {sink}: {e}"
    return text


def due(spec, now):
    """True when a five-field cron line matches this minute."""
    fields = str(spec).split()
    if len(fields) != 5:
        return False
    stamps = [now.minute, now.hour, now.day, now.month, (now.weekday() + 1) % 7]
    for field, value in zip(fields, stamps):
        hit = False
        for part in field.split(","):
            if part == "*":
                hit = True
            elif part.startswith("*/") and part[2:].isdigit():
                hit = value % int(part[2:]) == 0
            elif "-" in part:
                low, _, high = part.partition("-")
                hit = low.isdigit() and high.isdigit() and int(low) <= value <= int(high)
            elif part.isdigit():
                hit = value == int(part)
            if hit:
                break
        if not hit:
            return False
    return True


def passes(condition, text):
    """Whether a node should run at all, given what reached it."""
    if not condition:
        return True
    rule, _, argument = str(condition).partition(":")
    body = text or ""
    if rule == "not_empty":
        return bool(body.strip())
    if rule == "has_records":
        return bool(records_in(body))
    if rule == "contains":
        return argument.lower() in body.lower()
    if rule == "missing":
        return argument.lower() not in body.lower()
    if rule == "matches":
        try:
            return bool(re.search(argument, body, re.I))
        except re.error:
            return True
    return True


def run_approval(node, text, folder):
    """Hold the chain until a person says yes. Unattended, it records the request and stops."""
    node = Node.of(node)
    if sandbox.dry_run():
        return text  # a test run does not stop to ask a person
    os.makedirs(os.path.join(folder, "approvals"), exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    path = os.path.join(folder, "approvals", f"{stamp}.json")
    with open(path, "w") as f:
        json.dump({"asked": stamp, "prompt": node.prompt, "payload": text[:8000]}, f, indent=2)
    if sys.stdin.isatty():
        print(f"{OR}▸ {node.name or 'approval'}: {node.prompt}{O}")
        answer = input(f"{OR}approve? y/n {O}").strip().lower()
        if answer.startswith("y"):
            os.remove(path)
            return text
        return "error: rejected by a person"
    return f"error: waiting for approval, request written to {path}"


def run_output(node, text):
    node = Node.of(node)
    try:  # the box drawn around every node does the printing, this just tidies and filters
        data = json.loads(text)
    except Exception:
        return text
    field = node.dedupe
    if field:
        dropped = [0]

        def walk(item):
            if isinstance(item, list):
                for index in reversed(range(len(item))):
                    child = item[index]
                    if isinstance(child, dict) and field in child:
                        if not memory.is_new(str(child[field])):
                            item.pop(index)
                            dropped[0] += 1
                    else:
                        walk(child)
            elif isinstance(item, dict):
                for value in item.values():
                    walk(value)

        walk(data)
        if dropped[0]:
            print(f"{GR}{dropped[0]} record(s) already reported in an earlier run{O}")
    return json.dumps(data, indent=2)


def validate(data):
    """Every problem in a workflow file, in plain words, before anything runs."""
    return WorkflowSpec.of(data).problems()


class Workflow:
    def __init__(self, path):
        self.dir = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        yaml_path = os.path.join(path, "workflow.yaml") if os.path.isdir(path) else path
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        data = data if isinstance(data, dict) else {}
        # secrets first, then one pass of parsing: from here on the engine works with typed nodes
        self.spec = WorkflowSpec.of(dict(data, nodes=expand(data.get("nodes") or data.get("agents") or [])))
        guards = self.spec.safeguards
        self.guards = guards
        research.use_dir(self.dir)  # crawl memory and notes live with the workflow
        memory.use_dir(self.dir)
        sandbox.use_dir(self.dir, guards.allow_paths, guards.allow_shell,
                        guards.allow_private_network, guards.allow_email)
        for problem in self.spec.problems():
            print(f"{GR}warning: {problem}{O}")

        self.name = self.spec.name
        self.purpose = self.spec.purpose
        self.alwaysOn = self.spec.alwaysOn
        self.interval = self.spec.interval
        self.nodes = self.spec.nodes
        self.schedule = self.spec.schedule
        self.compute = self.spec.compute  # wait for a quiet machine before starting a cycle
        self.queues = {}
        self.threads = {}
        self.stop = threading.Event()
        self.dry = False          # a test run: reads are real, side effects are mocked
        self.run_id = None        # set while the studio is watching this run
        self.node_now = ""
        self.agents = {}
        for node in self.nodes:
            if node.kind != "agent":
                continue
            tools = [BY_NAME[t] for t in node.tool_names if t in BY_NAME]
            dispatch = {}
            for server in node.mcp:  # every tool the server offers, handed to this agent
                try:
                    schemas, calls = mcp.connect(server.url, server.prefix)
                    tools += schemas
                    dispatch.update(calls)
                    print(f"{GR}{node.name}: {len(calls)} tool(s) from {server.url}{O}")
                except Exception as e:
                    print(f"{GR}{node.name}: could not reach {server.url}: {e}{O}")
            self.agents[node.name] = Agent(
                model=node.model,
                name=node.name,
                system_prompt=node.system_prompt,
                tools=tools,
                output_format=node.output_schema or ("json" if node.export_json else None),
                dispatch=dispatch,
                require_tools=node.require_tools,
                on_tool=self._tool_hook,
            )

    def _point_tools_here(self):
        """Every worker thread and every child workflow leaves the tools pointed at itself. Take them back."""
        research.use_dir(self.dir)
        memory.use_dir(self.dir)
        sandbox.use_dir(self.dir, self.guards.allow_paths, self.guards.allow_shell,
                        self.guards.allow_private_network, self.guards.allow_email, dry_run=self.dry)

    def _emit(self, **fields):
        """One event onto the bus the studio is streaming, when a studio asked for this run."""
        if not self.run_id:
            return None
        return events.BUS.publish(run_id=self.run_id, workflow=os.path.basename(self.dir), **fields)

    def _tool_hook(self, call):
        self._emit(type="tool_call", node=self.node_now, tool=call.get("tool", ""),
                   args=call.get("args") or {}, result=str(call.get("result"))[:2000],
                   ms=call.get("ms"))

    def _async_loop(self, node, seed):
        self._point_tools_here()  # thread local, so every worker points at this workflow
        box = self.queues[node.name]
        while not self.stop.is_set():
            box.put(self._fire(node, seed))
            if self.stop.wait(node.interval):
                break

    def _start_async(self, node, seed):
        if node.name in self.threads:
            return
        self.queues[node.name] = queue.Queue()
        thread = threading.Thread(target=self._async_loop, args=(node, seed), daemon=True)
        thread.start()
        self.threads[node.name] = thread
        print(f"{OR}▸ {node.name} async, every {node.interval}s{O}")

    def _drain(self, wait):
        """Whatever the async nodes have produced, as one payload."""
        items = []
        for box in self.queues.values():
            while True:
                try:
                    items.append(box.get_nowait())
                except queue.Empty:
                    break
        for box in self.queues.values():  # nothing buffered yet, give the async nodes a moment
            if items or not wait:
                break
            try:
                items.append(box.get(timeout=wait))
            except queue.Empty:
                pass
        return Payload.of("\n".join(str(item) for item in items))

    def _fire(self, node, current):
        """Run one node on the payload that reached it, and hand back the payload it produced."""
        current = Payload.of(current)
        kind = node.kind
        if kind == "approval":
            return Payload.of(run_approval(node, current.text, self.dir), node.name)
        if kind == "workflow":
            child = Workflow(os.path.join(os.path.dirname(self.dir), node.ref))
            result = child.run_once()
            self._point_tools_here()  # the child pointed the tools at itself, take them back
            return Payload.of(result, node.name)
        if kind == "agent" and node.map:
            return self._map(node, current)
        if kind == "agent":
            answer = self.agents[node.name].chat(current.text)
            if not node.output_schema:
                return Payload.of(answer, node.name)
            return Payload.of(verify_records(answer, strict=node.verify == "strict"), node.name)
        if kind == "input":
            return Payload.of(run_input(node), node.name)
        if kind == "output":
            return Payload.of(send_output(node, run_output(node, current.text), self.dir), node.name)
        return Payload.of(f"error: unknown node type '{kind}'", node.name)

    def run(self, tasks=None):
        if self.schedule and not tasks:
            print(f"{OR}▸ {self.name} on cron {self.schedule}, ctrl-c to stop{O}")
            fired = None
            while True:
                now = datetime.datetime.now().replace(second=0, microsecond=0)
                if now != fired and due(self.schedule, now) and self._machine_ready():
                    fired = now
                    self.run_once()
                try:
                    time.sleep(20)
                except KeyboardInterrupt:
                    self.stop.set()
                    return

        if self.alwaysOn and not tasks:
            cycle = 1
            while True:
                print(f"{OR}▸ {self.name} cycle {cycle}{O}")
                self.run_once()
                print(f"{OR}▸ sleeping {self.interval}s, ctrl-c to stop{O}")
                try:
                    time.sleep(self.interval)
                except KeyboardInterrupt:
                    self.stop.set()
                    print(f"\n{OR}▸ {self.name} stopped after {cycle} cycles{O}")
                    return
                cycle += 1

        if tasks:
            return [
                self.agents[task["agent"]].chat(task.get("user_message", ""))
                if task.get("agent") in self.agents
                else f"error: agent '{task.get('agent')}' not found"
                for task in tasks
            ]

        return self.run_once().wire()

    def _map(self, node, current):
        """Run this agent once per incoming record, side by side, and gather the answers."""
        records = current.records or [current.text]
        agent = self.agents[node.name]
        width = min(node.parallel, 8)
        print(f"{GR}{node.name} mapping over {len(records)} record(s), {width} at a time{O}")

        def one(record):
            clone = Agent(model=agent.model, name=agent.name, system_prompt=agent.system_prompt,
                          tools=agent.tools, output_format=agent.output_format, dispatch=agent.dispatch,
                          on_tool=agent.on_tool)
            self._point_tools_here()
            answer = clone.chat(json.dumps(record) if isinstance(record, dict) else str(record))
            agent.calls.extend(clone.calls)
            for key, count in clone.tokens.items():  # the node spent what its clones spent
                agent.tokens[key] = agent.tokens.get(key, 0) + count
            return answer

        with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
            answers = list(pool.map(one, records))
        merged = []
        for answer in answers:
            merged.extend(records_in(answer) or [{"output": answer}])
        return Payload.of({"records": merged}, node.name)

    def _machine_ready(self):
        limits = self.compute.limits()
        if not limits:
            return True
        ready, busy, _ = compute.available(limits)
        if not ready:
            print(f"{GR}{self.name} holding off, {'; '.join(busy)}{O}")
        return ready

    def run_once(self, run_id=None, mode="run", from_node=None, seed=None, control=None):
        """One pass through the nodes.

        run_id and control are what the studio passes in: every step is published as an event,
        pause holds between nodes, stop cancels what is left. mode "test" mocks every side effect.
        from_node and seed re-run one node onward with the input it had.
        """
        started = time.time()
        self.run_id, self.dry = run_id, mode == "test"
        self._point_tools_here()
        run_dir = os.path.join(self.dir, "runs", time.strftime("%Y-%m-%dT%H-%M-%S"))
        os.makedirs(run_dir, exist_ok=True)
        record = RunRecord(workflow=self.name, started=time.strftime("%Y-%m-%d %H:%M:%S"),
                           run_id=run_id, mode=mode, status="completed")
        totals = {"prompt": 0, "completion": 0, "total": 0}

        plan = [node for node in self.nodes if not node.disabled]
        first = 0
        if from_node:
            first = next((i for i, node in enumerate(plan) if node.name == from_node), 0)
        current = Payload.of(seed) if seed is not None else Payload()
        self._emit(type="run_started", mode=mode, from_node=from_node or "",
                   nodes=[{"name": n.name, "type": n.kind, "mode": str(n.mode),
                           "disabled": n.disabled} for n in self.nodes])

        def cancel(rest, why):
            for node in rest:
                record.nodes.append(NodeRecord(name=node.name, type=node.kind, mode="sync",
                                               status="cancelled", note=why))
                self._emit(type="node_completed", node=node.name, node_type=node.kind,
                           status="cancelled")

        last = len(plan) - 1
        for index, node in enumerate(plan):
            if index < first:
                continue
            if control and control.gate() == "stopped":
                record.status, record.stopped_at = "stopped", node.name
                cancel(plan[index:], "run was stopped")
                self._emit(type="run_stopped", at_node=node.name)
                break

            if node.is_async:
                self._start_async(node, current)
                record.nodes.append(NodeRecord(name=node.name, type=node.kind, mode="async",
                                               note="running in its own thread", status="success"))
                self._emit(type="node_completed", node=node.name, node_type=node.kind,
                           status="success", text="running in its own thread")
                continue
            if self.queues:  # async nodes feed the chain whatever they have produced
                fresh = self._drain(node.wait)
                if fresh.text:
                    current = fresh

            if not passes(node.when, current.text):
                print(f"{GR}skipping {node.name}, when: {node.when} did not hold{O}")
                record.nodes.append(NodeRecord(name=node.name, type=node.kind, mode="sync",
                                               skipped=str(node.when), status="skipped"))
                self._emit(type="node_completed", node=node.name, node_type=node.kind,
                           status="skipped", text=f"when: {node.when} did not hold")
                continue

            given, clock = current, time.time()
            self.node_now = node.name
            self._emit(type="node_started", node=node.name, node_type=node.kind, index=index,
                       text=redact(given.text)[:4000])
            agent = self.agents.get(node.name)
            for attempt in range(node.retry + 1):
                current = self._fire(node, given)
                if not current.failed:
                    break
                self._emit(type="node_failed", node=node.name, node_type=node.kind,
                           error=redact(current.text)[:1000], attempt=attempt + 1,
                           retries_left=node.retry - attempt, ms=int((time.time() - clock) * 1000))
                if attempt < node.retry:
                    print(f"{GR}{node.name} failed, retry {attempt + 1}{O}")
                    time.sleep(2 ** attempt)

            spent = {k: v for k, v in (agent.tokens if agent else {}).items()}
            for key in totals:
                totals[key] += int(spent.get(key, 0))
            verdict = (checks.validate_output(current.text, node.output_schema, agent.calls)
                       if agent else None)
            entry = NodeRecord(name=node.name, type=node.kind, mode="sync",
                               ms=int((time.time() - clock) * 1000), input=redact(given.text)[:4000],
                               output=redact(current.text)[:8000], failed=current.failed,
                               status="failed" if current.failed else "success",
                               tokens=spent or None, validation=verdict,
                               error=redact(current.text)[:1000] if current.failed else None)
            if agent:
                entry.model = agent.model
                entry.tool_calls = json.loads(redact(json.dumps(agent.calls)))
            record.nodes.append(entry)

            if self.dry and node.kind == "output" and node.sink != "print":
                self._emit(type="tool_call", node=node.name, tool=f"sink:{node.sink}",
                           args={"path": node.path or "", "url": redact(node.url or "")},
                           result=sandbox.mocked(
                               f"send {len(current.records) or 1} item(s) to {node.sink}"))
            self._emit(type="node_output", node=node.name, node_type=node.kind,
                       text=redact(current.text)[:8000], bytes=len(current.text),
                       records=len(current.records))
            self._emit(type="node_completed", node=node.name, node_type=node.kind,
                       status=entry.status, ms=entry.ms, tokens=spent, model=entry.model or "",
                       validation=verdict)

            box(node.name or node.kind, f"{node.kind} \u00b7 {node.mode}", redact(current.text))
            if index < last:
                link()

            if current.failed and node.on_error == "stop":
                record.status, record.stopped_at = "failed", node.name
                print(f"{GR}stopping, {node.name} failed and on_error is stop{O}")
                cancel(plan[index + 1:], f"{node.name} failed and on_error is stop")
                break

        record.ms = int((time.time() - started) * 1000)
        record.tokens = totals
        record.metrics = metrics.compute(self.spec.metrics, current.records)
        with open(os.path.join(run_dir, "run.json"), "w") as f:
            json.dump(record.file(), f, indent=2)
        if mode == "run":  # a test run never writes history
            metrics.append(self.dir, {
                "run_id": run_id or "", "at": started, "workflow": os.path.basename(self.dir),
                "name": self.name, "status": record.status, "ms": record.ms, "tokens": totals,
                "values": record.metrics, "records": len(current.records),
                "failed_nodes": [n.name for n in record.nodes if n.status == "failed"]})
        self._emit(type="run_completed", status=record.status, ms=record.ms, tokens=totals,
                   metrics=record.metrics or {})
        self._prune_runs()
        self.run_id = None
        return current

    def _prune_runs(self, keep=50):
        root = os.path.join(self.dir, "runs")
        old = sorted(os.listdir(root))[:-keep]
        for name in old:
            path = os.path.join(root, name)
            for leaf in os.listdir(path):
                os.remove(os.path.join(path, leaf))
            os.rmdir(path)


if __name__ == "__main__":
    Workflow("/home/dsneedy/Desktop/AGENT-WORKFLOW-ORCHESTRATOR/src/engine/workflows/stock_analysis_pipeline").run()
