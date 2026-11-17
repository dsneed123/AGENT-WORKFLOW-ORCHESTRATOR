import os

import sandbox

def read_file(path: str) -> str:
    """Read a text file and return its contents.

    Args:
        path: path to the file
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    try:
        with open(sandbox.resolve(path), "r") as f:
            return f.read()[:20000]
    except Exception as e:
        return f"error {e}"

def write_file(path: str, content: str) -> str:
    """Write text to a file, overwriting it.

    Args:
        path: path to the file
        content: text to write
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    try:
        with open(sandbox.resolve(path), "w") as f:
            f.write(content)
        return f"wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"error {e}"

def list_dir(path: str = ".") -> str:
    """List the files and folders in a directory.

    Args:
        path: directory to list
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    try:
        return "\n".join(sorted(os.listdir(sandbox.resolve(path)))) or "empty"
    except Exception as e:
        return f"error {e}"
