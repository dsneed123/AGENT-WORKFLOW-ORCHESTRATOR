"""Metrics a workflow declares, and the per-run history the dashboards read.

A workflow states what it wants measured:

    metrics:
      - key: confidence
        label: Avg Confidence
        agg: avg          # avg | sum | min | max | count | rate
        format: percent   # number | percent | ms | currency | count

After every run one line goes into metrics.jsonl beside runs/, so history outlives the
run folders (runs/ keeps the last 50) and a 24h/7d/30d range is a cheap read.
"""
import json
import os
import time

FILE = "metrics.jsonl"
RANGES = {"24h": 86400, "7d": 604800, "30d": 2592000, "all": None}


def compute(declared, records):
    """One value per declared metric, from the records a run produced."""
    out = {}
    for metric in declared or []:
        key, how = metric.key, metric.agg
        if how == "count":
            out[key] = len(records)
            continue
        numbers = []
        truths = 0
        for record in records:
            value = record.get(key)
            if isinstance(value, bool):
                truths += 1 if value else 0
            elif isinstance(value, (int, float)):
                numbers.append(float(value))
            elif isinstance(value, str):
                try:
                    numbers.append(float(value.strip().rstrip("%")))
                except ValueError:
                    pass
        if how == "rate":
            out[key] = round(truths / len(records), 4) if records else None
        elif not numbers:
            out[key] = None
        elif how == "avg":
            out[key] = round(sum(numbers) / len(numbers), 4)
        elif how == "sum":
            out[key] = round(sum(numbers), 4)
        elif how == "min":
            out[key] = min(numbers)
        elif how == "max":
            out[key] = max(numbers)
        else:
            out[key] = None
    return out


def append(folder, line):
    """Add one run's line to this workflow's metric history."""
    try:
        with open(os.path.join(folder, FILE), "a") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass  # a run must never fail because its metrics could not be filed


def read(folder, since=None, limit=5000):
    """This workflow's metric lines, oldest first, optionally only those after a unix time."""
    path = os.path.join(folder, FILE)
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, "r") as f:
            for raw in f.readlines()[-limit:]:
                try:
                    line = json.loads(raw)
                except Exception:
                    continue
                if since is None or line.get("at", 0) >= since:
                    out.append(line)
    except Exception:
        return []
    return out


def since_for(window):
    seconds = RANGES.get(window, 86400)
    return None if seconds is None else time.time() - seconds


def _summary(lines):
    if not lines:
        return {"runs": 0, "success_rate": None, "avg_ms": None, "tokens": 0}
    good = sum(1 for line in lines if line.get("status") == "completed")
    durations = [line.get("ms", 0) for line in lines if line.get("ms")]
    return {"runs": len(lines),
            "success_rate": round(good / len(lines), 4),
            "avg_ms": int(sum(durations) / len(durations)) if durations else None,
            "tokens": sum(int((line.get("tokens") or {}).get("total") or 0) for line in lines)}


def system(folders, window="7d"):
    """Numbers across every workflow: runs a day, success rate, duration, tokens, failures by node.

    `previous` is the same summary for the window before this one, so a tile can say which
    way a number moved without the browser asking twice.
    """
    since = since_for(window)
    span = RANGES.get(window) or 0
    lines, earlier = [], []
    for folder in folders:
        for line in read(folder, None):
            at = line.get("at", 0)
            if since is None or at >= since:
                lines.append(line)
            elif span and at >= since - span:
                earlier.append(line)
    if not lines:
        return {"runs": 0, "per_day": [], "success_rate": None, "avg_ms": None,
                "tokens": 0, "failures_by_node": [], "recent": [], "previous": _summary(earlier)}
    per_day = {}
    failures = {}
    tokens = 0
    for line in lines:
        day = time.strftime("%Y-%m-%d", time.localtime(line.get("at", 0)))
        per_day[day] = per_day.get(day, 0) + 1
        tokens += int((line.get("tokens") or {}).get("total") or 0)
        for node in line.get("failed_nodes") or []:
            failures[node] = failures.get(node, 0) + 1
    return {
        **_summary(lines),
        "previous": _summary(earlier),
        "per_day": [{"label": day, "value": count} for day, count in sorted(per_day.items())],
        "failures_by_node": [{"label": node, "value": count}
                             for node, count in sorted(failures.items(), key=lambda kv: -kv[1])[:10]],
        "recent": sorted(lines, key=lambda line: -line.get("at", 0))[:40],
    }
