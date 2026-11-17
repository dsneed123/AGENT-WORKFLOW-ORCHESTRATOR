import subprocess

import sandbox

def run_shell_command(command: str) -> str:
    """Execute a shell command and return its output.

    Args:
        command: the shell command to run
    """
    refusal = sandbox.check_command(command)
    if refusal:
        return refusal
    try:
        result = subprocess.run(
            command,
            shell = True,
            cwd = sandbox.policy()["dir"],
            capture_output = True,
            text = True,
            timeout = 10,
        )
        if result.returncode == 0:
            return f"Output:\n{result.stdout}"

        else:
            return f"Error (exit code {result.returncode}):\n{result.stderr}"

    except subprocess.TimeoutExpired:
        return "error times out"

    except Exception as e:
        return f"error {e}"
