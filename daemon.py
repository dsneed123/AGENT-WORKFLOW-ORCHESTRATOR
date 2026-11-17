"""Run every always-on and scheduled workflow in one process, restarting any that crash.

Run: .venv/bin/python daemon.py
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src", "engine"))

import yaml  # noqa: E402

from workflow import Workflow  # noqa: E402
from workflow_creation import WORKFLOWS_DIR  # noqa: E402

STOP = threading.Event()


def scheduled():
    out = []
    for name in sorted(os.listdir(WORKFLOWS_DIR)):
        path = os.path.join(WORKFLOWS_DIR, name, "workflow.yaml")
        if not os.path.isfile(path):
            continue
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        if data.get("alwaysOn") or data.get("schedule"):
            out.append(name)
    return out


def supervise(folder):
    while not STOP.is_set():
        try:
            Workflow(os.path.join(WORKFLOWS_DIR, folder)).run()
        except Exception as e:
            print(f"{folder} crashed: {e}, restarting in 30s")
        if STOP.wait(30):
            return


if __name__ == "__main__":
    names = scheduled()
    if not names:
        print("no workflow has alwaysOn or schedule set")
        sys.exit(0)
    print(f"supervising {len(names)}: {', '.join(names)}")
    for name in names:
        threading.Thread(target=supervise, args=(name,), daemon=True).start()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        STOP.set()
        print("\nstopped")
