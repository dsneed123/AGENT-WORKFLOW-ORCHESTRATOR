"""The shapes this engine passes around: a workflow file, a node, what one node hands the next, a run record.

Everything here is a pydantic model, so a workflow is parsed and type checked once, at the edge, and the
engine works with attributes instead of dictionary lookups that silently return None.
"""
import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

NODE_TYPES = ("input", "agent", "output", "approval", "workflow")
AGGS = ("avg", "sum", "min", "max", "count", "rate")
FORMATS = ("number", "percent", "ms", "currency", "count")
SINKS = ("print", "file", "csv", "sqlite", "webhook", "slack")
SOURCES = {"text": ("value",), "file": ("path",), "api": ("url",), "mcp": ("url", "tool")}
COMPUTE_KEYS = ("max_cpu", "min_free_ram_gb", "max_gpu", "min_free_gpu_gb")
LOOSE = ConfigDict(extra="allow", protected_namespaces=(), populate_by_name=True)


def records_in(text):
    """The first array of records inside a JSON payload."""
    try:
        data = json.loads(text)
    except Exception:
        return []
    if isinstance(data, list):
        data = {"rows": data}
    if not isinstance(data, dict):
        return []
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


class Payload(BaseModel):
    """What one node hands the next, and what a child workflow hands its parent.

    The text is the wire: it is what an agent is given, what a sink writes, and what lands in the run
    record. The records are the same payload read as rows, so a mapping node or a sink never re-parses it.
    """
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    records: list[dict[str, Any]] = Field(default_factory=list)
    kind: Literal["text", "json"] = "text"
    node: str = ""  # the node that produced it

    @classmethod
    def of(cls, value, node=""):
        """Wrap whatever a node returned: a string, a dict, a list, or an already wrapped payload."""
        if isinstance(value, Payload):
            return value.model_copy(update={"node": node}) if node else value
        if isinstance(value, (dict, list)):
            text = json.dumps(value, indent=2)
        else:
            text = "" if value is None else str(value)
        rows = records_in(text)
        return cls(text=text, records=rows, kind="json" if rows else "text", node=node)

    @property
    def failed(self):
        return self.text.startswith("error")

    def wire(self):
        return self.text

    def __str__(self):
        return self.text


class Metric(BaseModel):
    """A number a workflow wants kept across runs, declared in its yaml under `metrics:`."""
    model_config = LOOSE
    key: str
    label: str = ""
    agg: str = "avg"
    format: str = "number"


class Point(BaseModel):
    """Where a node card sits on the studio canvas, when a person has moved it."""
    model_config = ConfigDict(extra="forbid")
    x: float = 0
    y: float = 0


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: str = ""


class NodeRecord(BaseModel):
    """One node's line in run.json. Keys the studio does not need are left out, not written as null."""
    model_config = ConfigDict(extra="allow")

    name: str = ""
    type: str = "agent"
    mode: str = "sync"
    ms: Optional[int] = None
    input: Optional[str] = None
    output: Optional[str] = None
    failed: Optional[bool] = None
    model: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    skipped: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None                     # success | failed | skipped | cancelled
    tokens: Optional[dict[str, int]] = None
    validation: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    def line(self):
        return self.model_dump(exclude_none=True)


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    workflow: str = ""
    started: str = ""
    nodes: list[NodeRecord] = Field(default_factory=list)
    ms: Optional[int] = None
    stopped_at: Optional[str] = None
    run_id: Optional[str] = None
    mode: Optional[str] = None                       # run | test
    status: Optional[str] = None                     # completed | failed | stopped
    tokens: Optional[dict[str, int]] = None
    metrics: Optional[dict[str, Any]] = None

    def file(self):
        out = self.model_dump(exclude_none=True)
        out["nodes"] = [n.line() for n in self.nodes]
        return out


class Safeguards(BaseModel):
    model_config = LOOSE
    allow_shell: bool = False
    allow_email: bool = False
    allow_private_network: bool = False
    allow_paths: list[str] = Field(default_factory=list)


class ComputeLimits(BaseModel):
    """How quiet the machine must be before a cycle starts. Anything else here is a limit we do not know."""
    model_config = LOOSE
    max_cpu: Optional[float] = None
    min_free_ram_gb: Optional[float] = None
    max_gpu: Optional[float] = None
    min_free_gpu_gb: Optional[float] = None

    def limits(self):
        return {k: v for k, v in self.model_dump(include=set(COMPUTE_KEYS)).items() if v is not None}

    def unknown(self):
        return list(self.model_extra or {})


class McpServer(BaseModel):
    model_config = LOOSE
    url: str = ""
    prefix: str = ""


class Node(BaseModel):
    """One step of a workflow. The keys that only matter to one node type are typed here too, so the
    engine reads node.sink or node.value instead of guessing what a dictionary holds."""
    model_config = LOOSE

    name: str = "<unnamed>"
    type: Any = "agent"
    mode: Any = "sync"

    # flow control, any node
    when: Optional[str] = None
    retry: int = 0
    on_error: Literal["stop", "continue"] = "continue"
    interval: int = 60          # async only
    wait: float = 0             # output only, seconds to wait on async nodes

    # input
    source: Any = "text"
    value: str = ""
    path: Optional[str] = None
    url: Optional[str] = None
    method: str = "GET"
    headers: Optional[dict[str, Any]] = None
    body: Any = None
    tool: Optional[str] = None
    arguments: Optional[dict[str, Any]] = None

    # agent
    model: Optional[str] = None
    system_prompt: str = ""
    tools: Any = Field(default_factory=list)
    require_tools: list[str] = Field(default_factory=list)
    mcp: list[McpServer] = Field(default_factory=list)
    output_schema: Optional[dict[str, Any]] = Field(default=None, alias="schema")
    export_json: bool = False
    verify: Optional[str] = None
    map: bool = False
    parallel: int = 4

    # studio
    disabled: bool = False      # kept in the file, stepped over by the engine
    layout: Optional[Point] = None

    # approval / child workflow
    prompt: str = "Approve this?"
    ref: Optional[str] = None

    # output
    sink: str = "print"
    table: str = "records"
    dedupe: Optional[str] = None

    @classmethod
    def of(cls, node):
        """Accept a node that is already parsed, or the raw block of keys from the yaml."""
        return node if isinstance(node, Node) else cls.model_validate(node or {})

    @property
    def kind(self):
        return self.type if isinstance(self.type, str) else str(self.type)

    @property
    def tool_names(self):
        return [t for t in self.tools if isinstance(t, str)] if isinstance(self.tools, list) else []

    @property
    def is_async(self):
        return self.mode == "async"


class WorkflowSpec(BaseModel):
    """A whole workflow.yaml, parsed once. `problems` says in plain words what is wrong with it."""
    model_config = LOOSE

    name: str = "unnamed_workflow"
    purpose: str = ""
    alwaysOn: bool = False
    interval: int = 300
    schedule: Optional[str] = None
    compute: ComputeLimits = Field(default_factory=ComputeLimits)
    safeguards: Safeguards = Field(default_factory=Safeguards)
    metrics: list[Metric] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    raw_nodes: list[Any] = Field(default_factory=list)  # kept as written, so junk can be reported not crash

    @model_validator(mode="before")
    @classmethod
    def _gather(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        raw = data.get("nodes") or data.get("agents") or []
        raw = list(raw) if isinstance(raw, list) else [raw]
        data["raw_nodes"] = raw
        data["nodes"] = [n for n in raw if isinstance(n, dict)]
        for key in ("compute", "safeguards"):
            if data.get(key) is None or not isinstance(data.get(key), dict):
                data.pop(key, None)
        return data

    @classmethod
    def of(cls, data):
        return data if isinstance(data, WorkflowSpec) else cls.model_validate(data if isinstance(data, dict) else {})

    def problems(self):
        """Every problem in this workflow, in plain words, before anything runs."""
        from agent import BY_NAME  # late, so nothing here needs a model runtime to be importable

        if not self.raw_nodes:
            return ["workflow has no nodes"]
        problems, seen = [], set()
        parsed = iter(self.nodes)
        for raw in self.raw_nodes:
            if not isinstance(raw, dict):
                problems.append(f"node {raw!r} is not a block of keys")
                continue
            node = next(parsed)
            name, kind = node.name, node.kind
            if name in seen:
                problems.append(f"two nodes are both called {name}")
            seen.add(name)
            if kind not in NODE_TYPES:
                problems.append(f"{name}: unknown node type '{kind}'")
            if node.mode not in ("sync", "async"):
                problems.append(f"{name}: mode must be sync or async")
            if node.is_async and "interval" not in raw:
                problems.append(f"{name}: async node has no interval, it will hammer every 60s by default")
            if kind == "agent":
                if not isinstance(node.tools, list):
                    problems.append(f"{name}: tools must be a list of names")
                    node.tools = []
                if not node.model:
                    problems.append(f"{name}: agent has no model")
                for tool in node.require_tools:
                    if tool not in node.tool_names:
                        problems.append(f"{name}: require_tools lists '{tool}' but it is not in tools")
                for tool in node.tool_names:
                    if tool not in BY_NAME:
                        problems.append(f"{name}: unknown tool '{tool}', pick from {', '.join(BY_NAME)}")
            elif kind in ("approval", "workflow"):
                if kind == "workflow" and not node.ref:
                    problems.append(f"{name}: workflow node needs a ref naming another workflow folder")
            else:
                if node.output_schema is not None:
                    problems.append(f"{name}: only agent nodes can carry a schema")
                if kind == "output":
                    if node.sink not in SINKS:
                        problems.append(f"{name}: unknown sink '{node.sink}'")
                    elif node.sink in ("webhook", "slack") and not node.url:
                        problems.append(f"{name}: {node.sink} sink needs a url")
                if kind == "input":
                    source = node.source
                    if not isinstance(source, str) or source not in SOURCES:
                        problems.append(f"{name}: unknown input source '{source}'")
                    else:
                        for field in SOURCES[source]:
                            if not getattr(node, field, None):
                                problems.append(f"{name}: input source {source} needs a {field}")
        for metric in self.metrics:
            if metric.agg not in AGGS:
                problems.append(f"metrics: '{metric.agg}' is not an aggregation this engine knows")
            if metric.format not in FORMATS:
                problems.append(f"metrics: '{metric.format}' is not a format this engine knows")
        for key in self.compute.unknown():
            problems.append(f"compute: '{key}' is not a limit this engine knows")
        if self.schedule and len(str(self.schedule).split()) != 5:
            problems.append(f"schedule '{self.schedule}' is not five cron fields")
        external = [n for n in self.nodes if n.sink in ("webhook", "slack")]
        if external and not any(n.kind == "approval" for n in self.nodes):
            problems.append(f"{external[0].name}: sends outside this machine with no approval node before it")
        last = self.raw_nodes[-1]
        if not isinstance(last, dict) or last.get("type") != "output":
            problems.append("workflow does not end with an output node")
        return problems
