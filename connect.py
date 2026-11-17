"""Open another machine's AWO Studio in your browser, over ssh.

    .venv/bin/python connect.py 10.0.0.5
    .venv/bin/python connect.py alice@10.0.0.5 --path ~/code/AGENT-WORKFLOW-ORCHESTRATOR

It logs in with ssh, starts the studio there if it is not already up, forwards the port
back here, and opens http://127.0.0.1:8740. The remote studio stays on its own loopback,
so nothing is exposed to the network and no token is needed: ssh is the lock.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser

FIND_AT = '[ -f "{path}/studio.py" ] && echo "{path}"; exit 0'

FIND_ANY = (
    'for d in "$HOME/AGENT-WORKFLOW-ORCHESTRATOR" "$HOME/Desktop/AGENT-WORKFLOW-ORCHESTRATOR" '
    '"$HOME/code/AGENT-WORKFLOW-ORCHESTRATOR" "$HOME/src/AGENT-WORKFLOW-ORCHESTRATOR"; do '
    '[ -f "$d/studio.py" ] && echo "$d" && exit 0; done; '
    'timeout 10 find "$HOME" -maxdepth 3 -name studio.py -path "*AGENT-WORKFLOW*" 2>/dev/null '
    '| head -1 | xargs -r dirname'
)

START = (
    'cd "{dir}" || exit 1; '
    'PY="{dir}/.venv/bin/python"; [ -x "$PY" ] || PY=python3; '
    # a port probe, not pgrep: the ssh command line itself contains "studio.py <port>"
    'up() {{ (exec 3<>/dev/tcp/127.0.0.1/{port}) 2>/dev/null; }}; '
    'up || (nohup "$PY" studio.py {port} > "{dir}/studio.log" 2>&1 &); '
    'for i in 1 2 3 4 5 6 7 8 9 10 11 12; do up && break; sleep 0.5; done; '
    'up && echo AWO_UP || {{ echo AWO_FAILED; tail -5 "{dir}/studio.log" 2>/dev/null; }}'
)


def listening(port, host="127.0.0.1"):
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def main():
    parser = argparse.ArgumentParser(description="Open a remote AWO Studio over ssh")
    parser.add_argument("target", help="an ip address, or user@ip")
    parser.add_argument("--path", default="", help="where the project lives on that machine")
    parser.add_argument("--port", type=int, default=8740, help="port the studio uses over there")
    parser.add_argument("--local-port", type=int, default=0, help="port to use here, defaults to the same")
    parser.add_argument("--ssh", default=os.environ.get("AWO_SSH", "ssh"), help="ssh command to use")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    host = args.target if "@" in args.target else f"{os.environ.get('USER', 'root')}@{args.target}"
    local_port = args.local_port or args.port
    ssh = args.ssh.split()
    common = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8"]

    if listening(local_port):
        print(f"something already answers on 127.0.0.1:{local_port} here. Pick another with --local-port.")
        return 1

    print(f"finding the project on {host} ...")
    look = FIND_AT.format(path=args.path.rstrip("/")) if args.path else FIND_ANY
    found = subprocess.run(ssh + common + [host, look], capture_output=True, text=True)
    if found.returncode != 0:
        print(f"could not reach {host}:\n{found.stderr.strip()}")
        return 1
    remote_dir = found.stdout.strip().splitlines()[-1] if found.stdout.strip() else ""
    if not remote_dir:
        where = f"at {args.path} on {host}" if args.path else f"on {host}"
        print(f"no studio.py found {where}." +
              ("" if args.path else " Point at it with --path."))
        return 1
    print(f"found {remote_dir}")

    started = subprocess.run(ssh + common + [host, START.format(dir=remote_dir, port=args.port)],
                             capture_output=True, text=True)
    if "AWO_UP" not in started.stdout:
        print(f"the studio would not start over there:\n{started.stdout.strip()}\n{started.stderr.strip()}")
        return 1
    print(f"studio running on {host}:{args.port}")

    tunnel = subprocess.Popen(
        ssh + common + ["-N", "-L", f"{local_port}:127.0.0.1:{args.port}", host],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    url = f"http://127.0.0.1:{local_port}"
    for _ in range(40):
        if listening(local_port):
            break
        if tunnel.poll() is not None:
            print(f"the tunnel closed:\n{(tunnel.stderr.read() or '').strip()}")
            return 1
        time.sleep(0.25)
    else:
        tunnel.terminate()
        print("the tunnel never came up")
        return 1

    print(f"\n  {url}  <- {host}\n\nctrl-c to disconnect. The remote studio keeps running.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        tunnel.wait()
    except KeyboardInterrupt:
        tunnel.terminate()
        print("\ndisconnected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
