"""What this machine has spare right now, so a workflow can wait for a quiet moment."""
import os
import subprocess


def _gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    except Exception:
        return None, None
    if out.returncode != 0 or not out.stdout.strip():
        return None, None
    busiest, free = None, None
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if parts and parts[0].isdigit():
            busiest = max(busiest or 0, int(parts[0]))
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            spare = (int(parts[2]) - int(parts[1])) / 1024
            free = spare if free is None else max(free, spare)
    return busiest, free


def snapshot():
    """CPU load, free memory and GPU pressure, as plain numbers."""
    cores = os.cpu_count() or 1
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    free_ram = None
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    free_ram = int(line.split()[1]) / 1024 / 1024
                    break
    except Exception:
        pass
    gpu_percent, gpu_free = _gpu()
    return {"cpu_percent": round(100 * load / cores, 1), "load": round(load, 2), "cores": cores,
            "free_ram_gb": None if free_ram is None else round(free_ram, 1),
            "gpu_percent": gpu_percent, "gpu_free_gb": None if gpu_free is None else round(gpu_free, 1)}


def available(limits, now=None):
    """Whether the machine is quiet enough to start, and why not when it is busy."""
    state = now or snapshot()
    busy = []
    if limits.get("max_cpu") is not None and state["cpu_percent"] > limits["max_cpu"]:
        busy.append(f"cpu at {state['cpu_percent']}% over {limits['max_cpu']}%")
    if limits.get("min_free_ram_gb") is not None and state["free_ram_gb"] is not None \
            and state["free_ram_gb"] < limits["min_free_ram_gb"]:
        busy.append(f"only {state['free_ram_gb']}GB ram free, wants {limits['min_free_ram_gb']}GB")
    if limits.get("max_gpu") is not None and state["gpu_percent"] is not None \
            and state["gpu_percent"] > limits["max_gpu"]:
        busy.append(f"gpu at {state['gpu_percent']}% over {limits['max_gpu']}%")
    if limits.get("min_free_gpu_gb") is not None and state["gpu_free_gb"] is not None \
            and state["gpu_free_gb"] < limits["min_free_gpu_gb"]:
        busy.append(f"only {state['gpu_free_gb']}GB gpu memory free, wants {limits['min_free_gpu_gb']}GB")
    return (not busy), busy, state
