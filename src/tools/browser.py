import json
import os
import re
import subprocess

import research
import sandbox

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_fetch.mjs")


def browser_get(url: str) -> str:
    """Open a page in a real browser and return its text. Use for sites that need JavaScript to render.

    Args:
        url: the full URL to open
    """
    refusal = sandbox.check_url(url)
    if refusal:
        return refusal
    st = research.state()
    if research.key(url) in st["fetched"]:
        return f"skipped, already read {url}, go somewhere new"
    try:
        done = subprocess.run(["node", SCRIPT, url], capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        return "error: node is not installed, browser_get cannot run"
    except subprocess.TimeoutExpired:
        return f"error: {url} took too long to render"
    if done.returncode != 0:
        return f"error rendering {url}: {done.stderr.strip()[:300]}"
    try:
        page = json.loads(done.stdout)
    except Exception:
        return f"error: browser returned nothing for {url}"
    st["fetched"][research.key(url)] = None
    for link in page.get("links", []):  # feed the crawl frontier like http_get does
        research._harvest(f'href="{link}"')
    text = re.sub(r"\s+", " ", page.get("text", "")).strip()[:20000]
    st["text"][research.key(url)] = text
    while len(st["text"]) > 60:
        st["text"].pop(next(iter(st["text"])))
    research._save()
    return text or f"{url} rendered but had no text"
