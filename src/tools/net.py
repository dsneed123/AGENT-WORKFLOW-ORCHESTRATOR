"""Reaching other systems: any HTTP API, feeds, screenshots, email."""
import json
import os
import re
import smtplib
import subprocess
import xml.etree.ElementTree as ET
from email.message import EmailMessage

import httpx

import research
import sandbox

SHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_shot.mjs")


def http_request(method: str, url: str, body: str = "", headers: str = "") -> str:
    """Call any HTTP API and return the response body. Use this for REST endpoints of other systems.

    Args:
        method: GET, POST, PUT, PATCH or DELETE
        url: the full URL
        body: JSON string to send, leave empty for GET
        headers: JSON object of extra headers, for example {"Authorization": "Bearer ..."}
    """
    refusal = sandbox.check_url(url)
    if refusal:
        return refusal
    if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return f"error: {method} is not a method this tool will send"
    if method.upper() != "GET" and sandbox.dry_run():
        return sandbox.mocked(f"{method.upper()} {url} with body {body[:200]}")
    try:
        sent = json.loads(body) if body.strip() else None
        extra = json.loads(headers) if headers.strip() else {}
    except Exception as e:
        return f"error: body and headers must be JSON, {e}"
    try:
        reply = httpx.request(method.upper(), url, json=sent, headers=extra, timeout=30, follow_redirects=True)
    except Exception as e:
        return f"error calling {url}: {e}"
    return f"HTTP {reply.status_code}\n{reply.text[:20000]}"


def rss_feed(url: str) -> str:
    """Read an RSS or Atom feed and list its newest items as title, date and link.

    Args:
        url: the feed URL
    """
    refusal = sandbox.check_url(url)
    if refusal:
        return refusal
    try:
        raw = httpx.get(url, timeout=20, follow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0"}).content
        root = ET.fromstring(raw)
    except Exception as e:
        return f"error reading {url}: {e}"
    items, state = [], research.state()
    for entry in list(root.iter())[:400]:
        tag = entry.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        field = {child.tag.split("}")[-1]: child for child in entry}
        link = field.get("link")
        href = (link.get("href") if link is not None and link.get("href") else
                (link.text if link is not None else "")) or ""
        title = (field.get("title").text if field.get("title") is not None else "").strip()
        when = next((field[k].text for k in ("pubDate", "updated", "published") if k in field), "")
        if href and research.key(href) in state["offered"]:
            continue
        if href:
            state["offered"][research.key(href)] = None
        items.append(f"{title} - {when} - {href}")
        if len(items) >= 20:
            break
    research._save()
    return "\n".join(items) or "no new items in that feed"


def screenshot(url: str, path: str = "screenshot.png") -> str:
    """Save a picture of a web page into the workflow folder.

    Args:
        url: the page to open
        path: file name to save it under
    """
    refusal = sandbox.check_url(url) or sandbox.check_path(path)
    if refusal:
        return refusal
    if sandbox.dry_run():
        return sandbox.mocked(f"save a picture of {url} to {path}")
    try:
        done = subprocess.run(["node", SHOT, url, sandbox.resolve(path)],
                              capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        return "error: node is not installed, screenshot cannot run"
    except subprocess.TimeoutExpired:
        return f"error: {url} took too long to render"
    if done.returncode != 0:
        return f"error taking screenshot: {done.stderr.strip()[:300]}"
    return f"saved {path}"


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. Only works when the workflow allows it and SMTP details are in the environment.

    Args:
        to: the recipient address
        subject: the subject line
        body: the message text
    """
    if not sandbox.policy().get("email"):
        return "error: email is off for this workflow, set safeguards.allow_email to turn it on"
    if sandbox.dry_run():
        return sandbox.mocked(f"email {to} with subject {subject!r}")
    host, user, password = (os.environ.get("AWO_SMTP_HOST"), os.environ.get("AWO_SMTP_USER"),
                            os.environ.get("AWO_SMTP_PASSWORD"))
    if not (host and user and password):
        return "error: set AWO_SMTP_HOST, AWO_SMTP_USER and AWO_SMTP_PASSWORD in the environment"
    if not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+$", to or ""):
        return f"error: {to} is not an email address"
    allowed = [d.strip().lower() for d in os.environ.get("AWO_SMTP_ALLOWED_DOMAINS", "").split(",") if d.strip()]
    if allowed and to.split("@")[-1].lower() not in allowed:
        return f"error: {to} is not in AWO_SMTP_ALLOWED_DOMAINS"
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = user, to, subject
    message.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("AWO_SMTP_PORT", "587")), timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(message)
    except Exception as e:
        return f"error sending email: {e}"
    return f"sent to {to}"
