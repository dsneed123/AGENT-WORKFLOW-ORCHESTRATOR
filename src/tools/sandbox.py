"""What a workflow's agents are allowed to touch. Deny by default, widened only by its own yaml."""
import ipaddress
import os
import re
import socket
import threading
from urllib.parse import urlparse

DANGEROUS = re.compile(
    r"\brm\s+-[rfRF]*[rfRF]\s+/(?!\w)|\bmkfs|\bdd\s+if=|\b(shutdown|reboot|halt|poweroff)\b"
    r"|:\(\)\s*\{.*\};:|\bchown\s+-R\s+/|\bchmod\s+-R\s+777\s+/"
    r"|curl[^|]*\|\s*(ba)?sh|wget[^|]*\|\s*(ba)?sh|>\s*/dev/(sd|nvme)", re.I)

POLICIES = {}
_current = threading.local()
DEFAULT = {"roots": [], "shell": False, "private_net": False, "email": False, "dir": None,
           "dry": False}


def use_dir(path, allow_paths=(), allow_shell=False, allow_private_network=False, allow_email=False,
            dry_run=False):
    """Point the guards at one workflow. Every thread that runs its tools must call this."""
    _current.dir = path
    POLICIES[path] = {
        "roots": [os.path.realpath(path)] + [os.path.realpath(os.path.expanduser(p)) for p in allow_paths],
        "shell": bool(allow_shell),
        "private_net": bool(allow_private_network),
        "email": bool(allow_email),
        "dir": path,
        "dry": bool(dry_run),
    }


def policy():
    path = getattr(_current, "dir", None)
    return POLICIES.get(path, DEFAULT)


def dry_run():
    """True on a test run: reads are real, anything that writes or sends is mocked."""
    return bool(policy().get("dry"))


def mocked(what):
    """The one line every mocked tool hands back, so a test run is never mistaken for a real one."""
    return f"[TEST] would {what}. Nothing was sent or written."


def resolve(path):
    """A relative path means inside the workflow folder, never the process's working directory."""
    here = policy()["dir"]
    return os.path.realpath(path if os.path.isabs(path) or not here else os.path.join(here, path))


def inside(path):
    real = resolve(path)
    return any(real == root or real.startswith(root + os.sep) for root in policy()["roots"])


def check_path(path):
    """None when the path is allowed, otherwise the refusal to hand back to the agent."""
    if not policy()["roots"]:
        return "error: no workflow is active, file tools are closed"
    if not inside(path):
        allowed = ", ".join(policy()["roots"])
        return f"error: {path} is outside what this workflow may touch ({allowed})"
    return None


def check_command(command):
    if not policy()["shell"]:
        return "error: shell is off for this workflow, set safeguards.allow_shell to turn it on"
    if DANGEROUS.search(command or ""):
        return f"error: refused, that command can destroy the machine: {command}"
    return None


def check_url(url):
    """Keep agents off loopback, private ranges and the cloud metadata address."""
    if policy()["private_net"]:
        return None
    host = urlparse(url).hostname
    if not host:
        return f"error: {url} has no host"
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except Exception:
        return f"error: cannot resolve {host}"
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return (f"error: {host} resolves to {address}, which is inside the network this machine sits on. "
                    f"Set safeguards.allow_private_network to allow it.")
    return None
