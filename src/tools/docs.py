"""Reading what a company actually keeps its information in: PDFs, Word files, spreadsheets, databases."""
import csv as csvlib
import io
import os
import re
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import sandbox

SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_pdf(path: str) -> str:
    """Read the text of a PDF file.

    Args:
        path: path to the .pdf file
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    try:
        done = subprocess.run(["pdftotext", "-layout", sandbox.resolve(path), "-"],
                              capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return "error: pdftotext is not installed on this machine"
    except subprocess.TimeoutExpired:
        return f"error: {path} took too long to read"
    if done.returncode != 0:
        return f"error reading {path}: {done.stderr.strip()[:200]}"
    return done.stdout.strip()[:20000] or f"{path} has no text, it may be scanned images"


def read_doc(path: str) -> str:
    """Read the text of a Word .docx file.

    Args:
        path: path to the .docx file
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    try:
        with zipfile.ZipFile(sandbox.resolve(path)) as book:
            root = ET.fromstring(book.read("word/document.xml"))
        lines = ["".join(t.text or "" for t in para.iter(WORD + "t")) for para in root.iter(WORD + "p")]
        return "\n".join(line for line in lines if line.strip())[:20000] or f"{path} has no text"
    except Exception as e:
        return f"error reading {path}: {e}"


def read_table(path: str) -> str:
    """Read a spreadsheet or csv and return its rows. Handles .csv, .tsv and .xlsx.

    Args:
        path: path to the .csv, .tsv or .xlsx file
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    real = sandbox.resolve(path)
    try:
        if real.lower().endswith(".xlsx"):
            with zipfile.ZipFile(real) as book:
                shared = []
                if "xl/sharedStrings.xml" in book.namelist():
                    strings = ET.fromstring(book.read("xl/sharedStrings.xml"))
                    shared = ["".join(t.text or "" for t in item.iter(SHEET + "t"))
                              for item in strings.findall(SHEET + "si")]
                sheets = sorted(n for n in book.namelist() if n.startswith("xl/worksheets/sheet"))
                if not sheets:
                    return f"error: {path} has no sheets"
                grid = ET.fromstring(book.read(sheets[0]))
            rows = []
            for row in grid.iter(SHEET + "row"):
                cells = []
                for cell in row.iter(SHEET + "c"):
                    value = cell.find(SHEET + "v")
                    text = "" if value is None else (value.text or "")
                    if cell.get("t") == "s" and text.isdigit() and int(text) < len(shared):
                        text = shared[int(text)]
                    cells.append(text)
                rows.append(cells)
                if len(rows) >= 200:
                    break
        else:
            with open(real, "r", newline="") as f:
                sample = f.read(4096)
                f.seek(0)
                delimiter = "\t" if real.lower().endswith(".tsv") or sample.count("\t") > sample.count(",") else ","
                rows = [row for _, row in zip(range(200), csvlib.reader(f, delimiter=delimiter))]
    except Exception as e:
        return f"error reading {path}: {e}"
    out = io.StringIO()
    csvlib.writer(out).writerows(rows)
    return out.getvalue()[:20000] or f"{path} is empty"


def sql_query(path: str, query: str) -> str:
    """Run one read-only SQL query against a sqlite database file and return the rows as csv.

    Args:
        path: path to the .db or .sqlite file
        query: a single SELECT statement
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    if not re.match(r"\s*(select|with)\b", query or "", re.I):
        return "error: only SELECT queries are allowed"
    try:
        db = sqlite3.connect(f"file:{sandbox.resolve(path)}?mode=ro", uri=True)
        cursor = db.execute(query)
        rows = cursor.fetchmany(500)
        names = [c[0] for c in cursor.description or []]
        db.close()
    except Exception as e:
        return f"error running query: {e}"
    out = io.StringIO()
    writer = csvlib.writer(out)
    writer.writerow(names)
    writer.writerows(rows)
    return out.getvalue()[:20000] or "no rows"


def search_files(pattern: str, path: str = ".") -> str:
    """Find which files under a folder contain some text, and show the matching lines.

    Args:
        pattern: the text or regular expression to look for
        path: folder to search, defaults to the workflow folder
    """
    refusal = sandbox.check_path(path)
    if refusal:
        return refusal
    try:
        needle = re.compile(pattern, re.I)
    except re.error as e:
        return f"error: bad pattern, {e}"
    hits = []
    for root, _, names in os.walk(sandbox.resolve(path)):
        for name in sorted(names):
            full = os.path.join(root, name)
            try:
                with open(full, "r", errors="ignore") as f:
                    for number, line in enumerate(f, 1):
                        if needle.search(line):
                            hits.append(f"{os.path.relpath(full, sandbox.resolve(path))}:{number}: {line.strip()[:200]}")
                            if len(hits) >= 200:
                                return "\n".join(hits)
            except Exception:
                continue
    return "\n".join(hits) or f"nothing matching {pattern}"
