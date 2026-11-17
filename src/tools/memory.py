import json
import os
import threading

STORES = {}            # workflow dir -> its notes
_current = threading.local()


def use_dir(path):
    """Point workflow memory at a workflow's own folder. Call this in every thread that uses it."""
    _current.dir = path
    if path in STORES:
        return
    try:
        with open(os.path.join(path, "memory.json"), "r") as f:
            STORES[path] = json.load(f)
    except Exception:
        STORES[path] = {"notes": {}, "emitted": []}


def store():
    path = getattr(_current, "dir", None)
    if path is None:
        path = os.path.dirname(os.path.abspath(__file__))
        use_dir(path)
    return STORES[path]


def _save():
    st = store()
    st["emitted"] = st["emitted"][-20000:]
    with open(os.path.join(_current.dir, "memory.json"), "w") as f:
        json.dump(st, f)


def is_new(record_key):
    """True the first time this workflow sees a record key, and it is remembered from then on."""
    st = store()
    if record_key in st["emitted"]:
        return False
    st["emitted"].append(record_key)
    _save()
    return True


def remember(key: str, value: str) -> str:
    """Save a note under a key so later runs of this workflow can read it back.

    Args:
        key: short name for the note
        value: the text to keep
    """
    store()["notes"][key] = value
    _save()
    return f"remembered {key}"


def recall(key: str) -> str:
    """Read back a note this workflow saved earlier, or say it is missing.

    Args:
        key: the name the note was saved under
    """
    return store()["notes"].get(key, f"nothing remembered under {key}")
