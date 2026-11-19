"""Typed run events, and the bus the studio streams them from.

One event per thing that happened inside a run. Every event carries the same envelope
(type, run_id, workflow, seq, at) and only the fields its type uses; `extra="forbid"`
keeps a typo out of the stream. The bus keeps the last events of each run, so a studio
that reloads mid-run replays what it missed instead of showing an empty workspace.
"""
import collections
import itertools
import queue
import threading
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

KIND = Literal[
    "run_started", "node_started", "node_output", "tool_call", "node_completed",
    "node_failed", "run_paused", "run_resumed", "run_stopped", "run_completed", "heartbeat",
]
HISTORY = 2000  # events kept per run for replay


class Event(BaseModel):
    """One line of a run's story. Fields outside the type's own set stay unset."""
    model_config = ConfigDict(extra="forbid")

    type: KIND
    run_id: str
    workflow: str = ""            # the workflow folder
    seq: int = 0
    at: float = 0                 # unix seconds, so the ui can order and age events

    # node scope
    node: str = ""
    node_type: str = ""
    index: Optional[int] = None

    # run scope
    mode: str = ""                # run | test
    from_node: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    status: str = ""              # success | failed | skipped | cancelled | stopped | completed
    ms: Optional[int] = None
    tokens: dict[str, int] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    at_node: str = ""

    # payloads
    text: str = ""
    bytes: Optional[int] = None
    records: Optional[int] = None
    model: str = ""
    validation: Optional[dict[str, Any]] = None

    # tool_call
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    result: str = ""

    # failure
    error: str = ""
    attempt: Optional[int] = None
    retries_left: Optional[int] = None


class Bus:
    """Fan-out of events to every open stream, plus a short history per run."""

    def __init__(self):
        self._subscribers = set()
        self._history = collections.defaultdict(lambda: collections.deque(maxlen=HISTORY))
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    def publish(self, **fields):
        event = Event(seq=next(self._seq), at=time.time(), **fields)
        line = event.model_dump()
        with self._lock:
            self._history[event.run_id].append(line)
            listeners = list(self._subscribers)
        for box in listeners:
            try:
                box.put_nowait(line)
            except queue.Full:
                pass  # a stream that cannot keep up catches up from history on reconnect
        return event

    def subscribe(self):
        box = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(box)
        return box

    def drop(self, box):
        with self._lock:
            self._subscribers.discard(box)

    def history(self, run_id=None, after=0):
        with self._lock:
            runs = [run_id] if run_id else list(self._history)
            lines = [line for run in runs for line in self._history.get(run, ()) if line["seq"] > after]
        return sorted(lines, key=lambda line: line["seq"])


BUS = Bus()
