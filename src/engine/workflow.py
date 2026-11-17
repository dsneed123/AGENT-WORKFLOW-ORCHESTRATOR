from agent import BY_NAME, Agent
import compute
import mcp
import memory
import sandbox
import research

#Dead code
"""
#agent1 = Agent("qwen3-coder-next:latest","agent1")
#agent2 = Agent("qwen3-coder-next:latest", "agent2")

if agent1.spin_up():
    ai_input = (agent1.chat("return mock data of webreseqrch of stock data and news including fake prices multiple stocks",""))
    print(ai_input)
    output = (agent2.chat("only return Json format for every stock ticker, price, confidence score umber up or down 1  being max -1 being bottom", ai_input))
    print(output_


if agent1.spin_up():
    ai_input = (agent1.chat("return mock data of webreseqrch of stock data and news including fake prices multiple stocks",""))
    print(ai_input)
    output = (agent2.chat("only return Json format for every stock ticker, price, confidence score umber up or down 1  being max -1 being bottom", ai_input))
    print(output)

"""

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
import compute

OR, GR, O = "\033[38;5;166m", "\033[38;5;245m", "\033[0m"
MAX_LINES = 20


def box(title, tag, text):
    width = min(shutil.get_terminal_size((100, 24)).columns, 100)
    inner = width - 4
    head = f"\u250c\u2500 {title} "
    tail = f" {tag} \u2510"
    print(f"{OR}{head}{'\u2500' * max(1, width - len(head) - len(tail))}{tail}{O}")
    lines = []
    for para in ((text or "").strip() or "(empty)").splitlines():
        lines += textwrap.wrap(para, inner) or [""]
    for line in lines[:MAX_LINES]:
        print(f"{OR}\u2502{O} {line:<{inner}} {OR}\u2502{O}")
    if len(lines) > MAX_LINES:
        more = f"... {len(lines) - MAX_LINES} more lines"
        print(f"{OR}\u2502{O} {more:<{inner}} {OR}\u2502{O}")
    print(f"{OR}\u2514{'\u2500' * (width - 2)}\u2518{O}")


def link():
    print(f"{OR}   \u2502{O}")
    print(f"{OR}   \u25bc{O}")


def run_input(node):
    source = node.get("source", "text")
    try:
        if source == "text":
            return str(node.get("value", ""))
        if source == "file":
            with open(node["path"], "r") as f:
                return f.read()
        if source == "api":
            return httpx.request(node.get("method", "GET"), node["url"], timeout=30,
                                 headers=node.get("headers") or {}, json=node.get("body"),
                                 follow_redirects=True).text
        if source == "mcp":
            return mcp.call(node["url"], node["tool"], node.get("arguments") or {})
        return f"error: unknown input source '{source}'"
    except Exception as e:
        return f"error {e}"


def _flat(quote):
    return re.sub(r"\s+", " ", (quote or "").lower()).strip()


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


def rows_of(text):
    """The first array of records inside a JSON payload."""
    try:
        data = json.loads(text)
    except Exception:
        return []
    if isinstance(data, list):
        data = {"rows": data}
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def send_output(node, text, folder):
    """Put the result somewhere other than the terminal."""
    sink = node.get("sink", "print")
    if sink == "print":
        return text
    rows = rows_of(text)
    default = {"file": "output.jsonl", "csv": "output.csv", "sqlite": "output.db"}.get(sink, "output.jsonl")
    path = os.path.join(folder, node.get("path", default))
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
            table = re.sub(r"\W", "_", node.get("table", "records"))
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
            url = node.get("url", "")
            if not url:
                return f"error: {sink} sink has no url"
            body = {"text": text[:3000]} if sink == "slack" else (json.loads(text) if text.strip().startswith(("{", "[")) else {"text": text})
            httpx.post(url, json=body, timeout=20).raise_for_status()
        else:
            return f"error: unknown sink '{sink}'"
        print(f"{GR}{node.get('name')} sent {len(rows) or 1} item(s) to {sink}{O}")
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
        return bool(rows_of(body))
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
    os.makedirs(os.path.join(folder, "approvals"), exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    path = os.path.join(folder, "approvals", f"{stamp}.json")
    with open(path, "w") as f:
        json.dump({"asked": stamp, "prompt": node.get("prompt", "Approve this?"), "payload": text[:8000]}, f, indent=2)
    if sys.stdin.isatty():
        print(f"{OR}\u25b8 {node.get('name', 'approval')}: {node.get('prompt', 'Approve this?')}{O}")
        answer = input(f"{OR}approve? y/n {O}").strip().lower()
        if answer.startswith("y"):
            os.remove(path)
            return text
        return "error: rejected by a person"
    return f"error: waiting for approval, request written to {path}"


def run_output(node, text):
    try:  # the box drawn around every node does the printing, this just tidies and filters
        data = json.loads(text)
    except Exception:
        return text
    field = node.get("dedupe")
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


SOURCES = {"text": ("value",), "file": ("path",), "api": ("url",), "mcp": ("url", "tool")}


def validate(data):
    """Every problem in a workflow file, in plain words, before anything runs."""
    problems = []
    nodes = data.get("nodes") or data.get("agents", [])
    if not nodes:
        return ["workflow has no nodes"]
    seen = set()
    for node in nodes:
        if not isinstance(node, dict):
            problems.append(f"node {node!r} is not a block of keys")
            continue
        name = str(node.get("name") or "<unnamed>")
        kind = node.get("type", "agent")
        if name in seen:
            problems.append(f"two nodes are both called {name}")
        seen.add(name)
        if kind not in ("input", "agent", "output", "approval", "workflow"):
            problems.append(f"{name}: unknown node type '{kind}'")
        if node.get("mode", "sync") not in ("sync", "async"):
            problems.append(f"{name}: mode must be sync or async")
        if node.get("mode") == "async" and not node.get("interval"):
            problems.append(f"{name}: async node has no interval, it will hammer every 60s by default")
        if kind == "agent":
            if not isinstance(node.get("tools", []), list):
                problems.append(f"{name}: tools must be a list of names")
                node["tools"] = []
            if not node.get("model"):
                problems.append(f"{name}: agent has no model")
            for tool in node.get("require_tools", []):
                if tool not in node.get("tools", []):
                    problems.append(f"{name}: require_tools lists '{tool}' but it is not in tools")
            for tool in node.get("tools", []):
                if tool not in BY_NAME:
                    problems.append(f"{name}: unknown tool '{tool}', pick from {', '.join(BY_NAME)}")
        elif kind in ("approval", "workflow"):
            if kind == "workflow" and not node.get("ref"):
                problems.append(f"{name}: workflow node needs a ref naming another workflow folder")
        else:
            if "schema" in node:
                problems.append(f"{name}: only agent nodes can carry a schema")
            if kind == "output":
                sink = node.get("sink", "print")
                if sink not in ("print", "file", "csv", "sqlite", "webhook", "slack"):
                    problems.append(f"{name}: unknown sink '{sink}'")
                elif sink in ("webhook", "slack") and not node.get("url"):
                    problems.append(f"{name}: {sink} sink needs a url")
            if kind == "input":
                source = node.get("source", "text")
                if not isinstance(source, str) or source not in SOURCES:
                    problems.append(f"{name}: unknown input source '{source}'")
                else:
                    for field in SOURCES[source]:
                        if not node.get(field):
                            problems.append(f"{name}: input source {source} needs a {field}")
    limits = data.get("compute") or {}
    for key in limits:
        if key not in ("max_cpu", "min_free_ram_gb", "max_gpu", "min_free_gpu_gb"):
            problems.append(f"compute: '{key}' is not a limit this engine knows")
    if data.get("schedule") and not due(data["schedule"], datetime.datetime.now()) and len(
            str(data["schedule"]).split()) != 5:
        problems.append(f"schedule '{data['schedule']}' is not five cron fields")
    external = [n for n in nodes if isinstance(n, dict) and n.get("sink") in ("webhook", "slack")]
    if external and not any(isinstance(n, dict) and n.get("type") == "approval" for n in nodes):
        problems.append(f"{external[0].get('name')}: sends outside this machine with no approval node before it")
    if not isinstance(nodes[-1], dict) or nodes[-1].get("type") != "output":
        problems.append("workflow does not end with an output node")
    return problems


class Workflow:
    def __init__(self, path):
        self.dir = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
        yaml_path = os.path.join(path, "workflow.yaml") if os.path.isdir(path) else path
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        guards = data.get("safeguards") or {}
        self.guards = guards
        research.use_dir(self.dir)  # crawl memory and notes live with the workflow
        memory.use_dir(self.dir)
        sandbox.use_dir(self.dir, guards.get("allow_paths", []),
                        guards.get("allow_shell", False), guards.get("allow_private_network", False),
                        guards.get("allow_email", False))
        for problem in validate(data):
            print(f"{GR}warning: {problem}{O}")

        self.name = data.get("name", "unnamed_workflow")
        self.purpose = data.get("purpose", "")
        self.alwaysOn = data.get("alwaysOn", False)
        self.interval = data.get("interval", 300)
        self.nodes = expand(data.get("nodes") or data.get("agents", []))
        self.schedule = data.get("schedule")
        self.compute = data.get("compute") or {}  # wait for a quiet machine before starting a cycle
        self.queues = {}
        self.threads = {}
        self.stop = threading.Event()
        self.agents = {}
        for node in self.nodes:
            if node.get("type", "agent") != "agent":
                continue
            tools = [BY_NAME[t] for t in node.get("tools", [])]
            dispatch = {}
            for server in node.get("mcp", []):  # every tool the server offers, handed to this agent
                try:
                    schemas, calls = mcp.connect(server["url"], server.get("prefix", ""))
                    tools += schemas
                    dispatch.update(calls)
                    print(f"{GR}{node['name']}: {len(calls)} tool(s) from {server['url']}{O}")
                except Exception as e:
                    print(f"{GR}{node['name']}: could not reach {server.get('url')}: {e}{O}")
            self.agents[node["name"]] = Agent(
                model=node["model"],
                name=node["name"],
                system_prompt=node.get("system_prompt", ""),
                tools=tools,
                output_format=node.get("schema") or ("json" if node.get("export_json") else None),
                dispatch=dispatch,
                require_tools=node.get("require_tools", []),
            )

    def _async_loop(self, node, seed):
        research.use_dir(self.dir)  # thread local, so every worker points at this workflow
        memory.use_dir(self.dir)
        sandbox.use_dir(self.dir, self.guards.get("allow_paths", []),
                        self.guards.get("allow_shell", False), self.guards.get("allow_private_network", False),
                        self.guards.get("allow_email", False))
        box = self.queues[node["name"]]
        while not self.stop.is_set():
            box.put(self._fire(node, seed))
            if self.stop.wait(node.get("interval", 60)):
                break

    def _start_async(self, node, seed):
        if node["name"] in self.threads:
            return
        self.queues[node["name"]] = queue.Queue()
        thread = threading.Thread(target=self._async_loop, args=(node, seed), daemon=True)
        thread.start()
        self.threads[node["name"]] = thread
        print(f"{OR}▸ {node['name']} async, every {node.get('interval', 60)}s{O}")

    def _drain(self, wait):
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
        return "\n".join(items)

    def _fire(self, node, current):
        kind = node.get("type", "agent")
        if kind == "approval":
            return run_approval(node, current, self.dir)
        if kind == "workflow":
            child = Workflow(os.path.join(os.path.dirname(self.dir), node["ref"]))
            result = child.run_once()
            research.use_dir(self.dir)  # the child pointed the tools at itself, take them back
            memory.use_dir(self.dir)
            sandbox.use_dir(self.dir, self.guards.get("allow_paths", []),
                            self.guards.get("allow_shell", False), self.guards.get("allow_private_network", False),
                        self.guards.get("allow_email", False))
            return result
        if kind == "agent" and node.get("map"):
            return self._map(node, current)
        if kind == "agent":
            answer = self.agents[node["name"]].chat(current)
            if not node.get("schema"):
                return answer
            return verify_records(answer, strict=node.get("verify") == "strict")
        if kind == "input":
            return run_input(node)
        if kind == "output":
            return send_output(node, run_output(node, current), self.dir)
        return f"error: unknown node type '{kind}'"

    def run(self, tasks=None):
        if self.schedule and not tasks:
            print(f"{OR}\u25b8 {self.name} on cron {self.schedule}, ctrl-c to stop{O}")
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

        return self.run_once()

    def _map(self, node, current):
        """Run this agent once per incoming record, side by side, and gather the answers."""
        records = rows_of(current) or [current]
        agent = self.agents[node["name"]]
        width = min(int(node.get("parallel", 4)), 8)
        print(f"{GR}{node['name']} mapping over {len(records)} record(s), {width} at a time{O}")

        def one(record):
            clone = Agent(model=agent.model, name=agent.name, system_prompt=agent.system_prompt,
                          tools=agent.tools, output_format=agent.output_format, dispatch=agent.dispatch)
            research.use_dir(self.dir)
            memory.use_dir(self.dir)
            sandbox.use_dir(self.dir, self.guards.get("allow_paths", []),
                            self.guards.get("allow_shell", False), self.guards.get("allow_private_network", False),
                        self.guards.get("allow_email", False))
            answer = clone.chat(json.dumps(record) if isinstance(record, dict) else str(record))
            agent.calls.extend(clone.calls)
            return answer

        with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
            answers = list(pool.map(one, records))
        merged = []
        for answer in answers:
            merged.extend(rows_of(answer) or [{"output": answer}])
        return json.dumps({"records": merged}, indent=2)

    def _machine_ready(self):
        if not self.compute:
            return True
        ready, busy, _ = compute.available(self.compute)
        if not ready:
            print(f"{GR}{self.name} holding off, {'; '.join(busy)}{O}")
        return ready

    def run_once(self):
        started = time.time()
        run_dir = os.path.join(self.dir, "runs", time.strftime("%Y-%m-%dT%H-%M-%S"))
        os.makedirs(run_dir, exist_ok=True)
        record = {"workflow": self.name, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "nodes": []}

        current = ""
        last = len(self.nodes) - 1
        for index, node in enumerate(self.nodes):
            if node.get("mode", "sync") == "async":
                self._start_async(node, current)
                record["nodes"].append({"name": node.get("name"), "type": node.get("type", "agent"),
                                        "mode": "async", "note": "running in its own thread"})
                continue
            if self.queues:  # async nodes feed the chain whatever they have produced
                fresh = self._drain(node.get("wait", 0))
                if fresh:
                    current = fresh

            if not passes(node.get("when"), current):
                print(f"{GR}skipping {node.get('name')}, when: {node.get('when')} did not hold{O}")
                record["nodes"].append({"name": node.get("name"), "type": node.get("type", "agent"),
                                        "mode": "sync", "skipped": str(node.get("when"))})
                continue

            given, clock = current, time.time()
            for attempt in range(node.get("retry", 0) + 1):
                current = self._fire(node, given)
                if not str(current).startswith("error"):
                    break
                if attempt < node.get("retry", 0):
                    print(f"{GR}{node.get('name')} failed, retry {attempt + 1}{O}")
                    time.sleep(2 ** attempt)

            failed = str(current).startswith("error")
            entry = {"name": node.get("name"), "type": node.get("type", "agent"), "mode": "sync",
                     "ms": int((time.time() - clock) * 1000), "input": redact(given)[:4000],
                     "output": redact(current)[:8000], "failed": failed}
            if node.get("name") in self.agents:
                entry["model"] = self.agents[node["name"]].model
                entry["tool_calls"] = json.loads(redact(json.dumps(self.agents[node["name"]].calls)))
            record["nodes"].append(entry)

            box(node.get("name", node.get("type", "agent")),
                f"{node.get('type', 'agent')} \u00b7 {node.get('mode', 'sync')}", redact(current))
            if index < last:
                link()

            if failed and node.get("on_error", "continue") == "stop":
                record["stopped_at"] = node.get("name")
                print(f"{GR}stopping, {node.get('name')} failed and on_error is stop{O}")
                break

        record["ms"] = int((time.time() - started) * 1000)
        with open(os.path.join(run_dir, "run.json"), "w") as f:
            json.dump(record, f, indent=2)
        self._prune_runs()
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
