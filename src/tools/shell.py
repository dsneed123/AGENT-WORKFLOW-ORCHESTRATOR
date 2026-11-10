import subprocess

def run_shell_command(command: str) -> str:
    #execute a shell command and return output

    try:
        result = subprocess.run(
            command,
            shell = True,
            capture_output = True,
            text = True,
            timeout = 10,
            
        )
        if result.returncode ==0:
            return f"Output:\m{result.stdout}"

        else:
            return f"Error (exit code {result.returncode}):\n{result.stderr}"

    except subprocess.TimeoutExpired:
        return "error times out"
    
    except Exception as e
        return f"error {e}"