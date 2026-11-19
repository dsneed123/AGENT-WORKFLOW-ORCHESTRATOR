"""Writing a workflow file from the studio: versions first, then validate, then save.

Every write snapshots the file it replaced into the workflow's versions/ folder, so any
change the chat or the canvas makes can be undone.
"""
import json
import os
import shutil
import time

import yaml

from workflow import validate

VERSIONS = "versions"
KEEP = 40


def _dir(folder):
    path = os.path.join(folder, VERSIONS)
    os.makedirs(path, exist_ok=True)
    return path


def snapshot(folder, label=""):
    """Keep the current workflow.yaml as a version, and return its name."""
    source = os.path.join(folder, "workflow.yaml")
    if not os.path.isfile(source):
        return None
    name = f"{time.strftime('%Y-%m-%dT%H-%M-%S')}{('-' + label) if label else ''}.yaml"
    shutil.copy2(source, os.path.join(_dir(folder), name))
    old = sorted(os.listdir(_dir(folder)))[:-KEEP]
    for leaf in old:
        os.remove(os.path.join(_dir(folder), leaf))
    return name


def versions(folder):
    """Every kept version, newest first, with its size and when it was taken."""
    path = _dir(folder)
    out = []
    for name in sorted(os.listdir(path), reverse=True):
        full = os.path.join(path, name)
        out.append({"version": name, "at": os.path.getmtime(full), "bytes": os.path.getsize(full),
                    "label": name.replace(".yaml", "").partition("-")[2][18:] or "edit"})
    return out


def read_version(folder, version):
    path = os.path.join(_dir(folder), os.path.basename(version))
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return f.read()


def apply_yaml(folder, text, label="chat"):
    """Validate a proposed workflow file and write it, keeping what it replaced."""
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        return {"success": False, "error": f"not valid yaml: {e}"}
    if not isinstance(data, dict):
        return {"success": False, "error": "a workflow must be a block of keys"}
    problems = validate(data)
    kept = snapshot(folder, label)
    with open(os.path.join(folder, "workflow.yaml"), "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return {"success": True, "warnings": problems, "version_kept": kept}


def create_from_yaml(root, text):
    """Save a proposed workflow as a new folder, never clobbering one that exists."""
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        return {"success": False, "error": f"not valid yaml: {e}"}
    if not isinstance(data, dict):
        return {"success": False, "error": "a workflow must be a block of keys"}
    name = str(data.get("name") or "unnamed")
    folder, n = os.path.join(root, name), 2
    while os.path.exists(folder):
        folder, n = os.path.join(root, f"{name}_{n}"), n + 1
    os.makedirs(folder)
    with open(os.path.join(folder, "workflow.yaml"), "w") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return {"success": True, "folder": os.path.basename(folder), "warnings": validate(data)}


def restore(folder, version):
    text = read_version(folder, version)
    if text is None:
        return {"success": False, "error": f"no version called {version}"}
    return apply_yaml(folder, text, label="restore")


def _nodes(data):
    key = "nodes" if data.get("nodes") else ("agents" if data.get("agents") else "nodes")
    data.setdefault(key, [])
    return key, data[key]


def node_action(folder, action, name, **extra):
    """The light editing the canvas offers: disable, duplicate, delete, move a node."""
    path = os.path.join(folder, "workflow.yaml")
    with open(path, "r") as f:
        text = f.read()
    data = yaml.safe_load(text) or {}
    key, nodes = _nodes(data)
    index = next((i for i, n in enumerate(nodes) if isinstance(n, dict) and n.get("name") == name), None)
    if index is None:
        return {"success": False, "error": f"no node called {name}"}
    node = nodes[index]

    if action == "disable":
        node["disabled"] = not node.get("disabled", False)
    elif action == "delete":
        nodes.pop(index)
    elif action == "duplicate":
        copy = json.loads(json.dumps(node))
        base = f"{name}_copy"
        taken = {n.get("name") for n in nodes if isinstance(n, dict)}
        new_name, n = base, 2
        while new_name in taken:
            new_name, n = f"{base}{n}", n + 1
        copy["name"] = new_name
        nodes.insert(index + 1, copy)
    elif action == "move":
        node["layout"] = {"x": round(float(extra.get("x", 0)), 1),
                          "y": round(float(extra.get("y", 0)), 1)}
    else:
        return {"success": False, "error": f"unknown action {action}"}

    data[key] = nodes
    dumped = yaml.dump(data, default_flow_style=False, sort_keys=False)
    label = action if action != "move" else ""
    if action == "move":  # repositioning is not worth a version of its own
        with open(path, "w") as f:
            f.write(dumped)
        return {"success": True, "warnings": validate(data)}
    return apply_yaml(folder, dumped, label=label)
