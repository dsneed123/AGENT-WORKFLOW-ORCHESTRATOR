import os
import sys
import threading
import webbrowser

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "engine"))
from workflow import Workflow
from workflow_creation import WORKFLOWS_DIR, create_workflow_from_ai

B, D, OR, GR, O = "\033[1m", "\033[2m", "\033[38;5;166m", "\033[38;5;245m", "\033[0m"

def listed():
    return sorted(d for d in os.listdir(WORKFLOWS_DIR)
                  if os.path.isfile(os.path.join(WORKFLOWS_DIR, d, "workflow.yaml")))

def show():
    files = listed()
    print(f"\n{OR}┏━{O} {B}AGENT WORKFLOW ORCHESTRATOR{O} {GR}{len(files)} workflows{O}")
    print(f"{OR}┃{O}  {GR}{WORKFLOWS_DIR}{O}\n{OR}┃{O}")
    for i, f in enumerate(files, 1):
        data = yaml.safe_load(open(os.path.join(WORKFLOWS_DIR, f, "workflow.yaml")))
        extras = [x for x in sorted(os.listdir(os.path.join(WORKFLOWS_DIR, f))) if x != "workflow.yaml"]
        print(f"{OR}┃{O}  {OR}{i:>2}{O}  {B}{data.get('name', f)}{O}  {GR}{' '.join(extras)}{O}")
        loop = f"  {OR}always on, every {data.get('interval', 300)}s{O}" if data.get("alwaysOn") else ""
        print(f"{OR}┃{O}      {GR}{data.get('purpose', '')}{O}{loop}")
        for node in data.get("nodes") or data.get("agents", []):
            kind = node.get("type", "agent")
            detail = ", ".join(node.get("tools") or []) or "no tools" if kind == "agent" else node.get("source", "print")
            mode = "async" if node.get("mode") == "async" else "sync "
            print(f"{OR}┃{O}      {GR}└{O} {mode} {kind:<7}{node.get('name', ''):<24}{GR}{node.get('model', ''):<26}{O}{OR}{detail}{O}")
        print(f"{OR}┃{O}")
    print(f"{OR}┗━{O} {GR}run <n>  ·  new  ·  ui [port]  ·  q{O}\n")

def launch_ui(port=8740):
    """Serve the studio and open it in a browser."""
    import studio
    url = f"http://127.0.0.1:{port}"
    print(f"\n{OR}▸ studio at {url}{O}  {GR}ctrl-c to stop{O}\n")
    threading.Timer(1.0, webbrowser.open, (url,)).start()
    studio.serve(port=port)
    print(f"{GR}studio stopped{O}")


def main():
    while True:
        show()
        try:
            parts = input(f"{OR}▸{O} ").strip().split(maxsplit=1)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not parts or parts[0] in ("q", "quit", "exit"):
            return 0
        if parts[0] == "run" and len(parts) == 2 and parts[1].isdigit():
            files = listed()
            i = int(parts[1])
            if 1 <= i <= len(files):
                print(f"\n{OR}▸ running {files[i - 1]}{O}\n")
                Workflow(os.path.join(WORKFLOWS_DIR, files[i - 1])).run()
            else:
                print(f"{OR}no workflow {i}{O}")
        elif parts[0] == "ui":
            launch_ui(int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 8740)
        elif parts[0] == "new":
            goal = parts[1] if len(parts) == 2 else input(f"{GR}goal:{O} ")
            print(f"{GR}building ...{O}")
            print(create_workflow_from_ai(user_goal=goal))
        else:
            print(f"{GR}run <n> | new [goal] | ui [port] | q{O}")

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in ("cli", "menu"):
        sys.exit(main())
    launch_ui(int(args[0]) if args and args[0].isdigit() else 8740)
