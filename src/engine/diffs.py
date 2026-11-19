"""The structural difference between the workflow on disk and the one the chat proposes.

The studio paints this on the canvas before anything is written: green added, red removed,
yellow modified. Edges in this engine are the order of the nodes, so a moved node shows up
as changed edges rather than as a changed field.
"""
import yaml

TOP = ("name", "purpose", "alwaysOn", "interval", "schedule", "compute", "safeguards", "metrics")


def _nodes(data):
    raw = (data or {}).get("nodes") or (data or {}).get("agents") or []
    return [n for n in raw if isinstance(n, dict)]


def _edges(nodes):
    return [(a.get("name", ""), b.get("name", "")) for a, b in zip(nodes, nodes[1:])]


def _changes(before, after):
    out = {}
    for field in sorted(set(before) | set(after)):
        if before.get(field) != after.get(field):
            out[field] = [before.get(field), after.get(field)]
    return out


def diff(old_yaml, new_yaml):
    """{nodes, edges, top, counts} between two workflow files, as plain data for the ui."""
    try:
        old = yaml.safe_load(old_yaml) or {}
    except Exception:
        old = {}
    try:
        new = yaml.safe_load(new_yaml) or {}
    except Exception as e:
        return {"error": f"the proposed file is not valid yaml: {e}"}

    before, after = _nodes(old), _nodes(new)
    by_name_before = {n.get("name", ""): n for n in before}
    by_name_after = {n.get("name", ""): n for n in after}

    nodes = []
    for name, node in by_name_after.items():
        if name not in by_name_before:
            nodes.append({"name": name, "status": "added", "type": node.get("type", "agent")})
        else:
            changed = _changes(by_name_before[name], node)
            if changed:
                nodes.append({"name": name, "status": "modified", "type": node.get("type", "agent"),
                              "changes": changed})
    for name, node in by_name_before.items():
        if name not in by_name_after:
            nodes.append({"name": name, "status": "removed", "type": node.get("type", "agent")})

    old_edges, new_edges = _edges(before), _edges(after)
    edges = ([{"from": a, "to": b, "status": "added"} for a, b in new_edges if (a, b) not in old_edges]
             + [{"from": a, "to": b, "status": "removed"} for a, b in old_edges if (a, b) not in new_edges])

    top = _changes({k: old.get(k) for k in TOP if k in old}, {k: new.get(k) for k in TOP if k in new})
    counts = {"added": sum(1 for n in nodes if n["status"] == "added"),
              "removed": sum(1 for n in nodes if n["status"] == "removed"),
              "modified": sum(1 for n in nodes if n["status"] == "modified"),
              "edges": len(edges), "settings": len(top)}
    return {"nodes": nodes, "edges": edges, "top": top, "counts": counts,
            "same": not (nodes or edges or top)}
