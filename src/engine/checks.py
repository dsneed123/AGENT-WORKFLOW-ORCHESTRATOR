"""What the studio shows under a node's "validation" line: did this output hold up?

Deterministic checks only, run in code after the node answered: the shape its schema asked
for, filler the model types when it has nothing, links it never opened, and the same tool
call made over and over. No model judges another model here.
"""
import json
import re

FILLER = re.compile(
    r"\bas an ai\b|\bi (?:cannot|can't|am unable to)\b|\blorem ipsum\b|\bplaceholder\b"
    r"|\byour (?:name|company) here\b|\bexample\.com\b|\btodo\b|\bfill in\b|\bn/?a\b", re.I)


def _records(payload):
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    return []


def _shape(payload, schema, problems):
    """The parts of a JSON Schema this engine checks itself: type, required keys, array items."""
    kind = schema.get("type")
    if kind == "object" and not isinstance(payload, dict):
        problems.append(f"schema wants an object, got {type(payload).__name__}")
        return
    if kind == "array" and not isinstance(payload, list):
        problems.append(f"schema wants an array, got {type(payload).__name__}")
        return
    if isinstance(payload, dict):
        for field in schema.get("required", []):
            if field not in payload:
                problems.append(f"schema requires '{field}', which is missing")
        for name, rule in (schema.get("properties") or {}).items():
            if name in payload and isinstance(rule, dict):
                _shape(payload[name], rule, problems)
    if isinstance(payload, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(payload[:40]):
            before = len(problems)
            _shape(item, schema["items"], problems)
            for i in range(before, len(problems)):
                problems[i] = f"record {index + 1}: {problems[i]}"


def validate_output(text, schema=None, tool_calls=()):
    """{"ok": bool, "problems": [plain words]} for one node's output."""
    problems = []
    body = text or ""
    payload = None
    try:
        payload = json.loads(body)
    except Exception:
        if schema:
            problems.append("node has a schema but its output is not JSON")

    if schema and payload is not None:
        _shape(payload, schema, problems)

    hit = FILLER.search(body)
    if hit:
        problems.append(f"output contains filler text: {hit.group(0)!r}")

    records = _records(payload) if payload is not None else []
    unverified = [r for r in records if r.get("verified") is False]
    for record in unverified[:5]:
        link = next((v for v in record.values() if isinstance(v, str) and v.startswith("http")), "a record")
        problems.append(f"{link} did not hold up: {record.get('evidence', 'unverified')}")
    if len(unverified) > 5:
        problems.append(f"{len(unverified) - 5} more unverified record(s)")

    seen = {}
    for call in tool_calls or ():
        signature = (call.get("tool"), json.dumps(call.get("args"), sort_keys=True))
        seen[signature] = seen.get(signature, 0) + 1
    for (tool, args), count in seen.items():
        if count > 2:
            problems.append(f"called {tool} {count} times with the same arguments {args[:80]}")

    return {"ok": not problems, "problems": problems}
