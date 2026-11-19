"""Crawling as code, not as a chain of model calls.

An agent says where to start and how far. This walks the site: breadth first, one page per link,
obeying robots.txt, one request per host at a time, and stops at whichever cap it hits first. The
report says which cap fired, so a thin crawl is never mistaken for a thin site.

Every page it reads is stored as evidence in the workflow's crawl memory, so a record that quotes a
crawled page can still be checked against what was actually on it.

Non-goals: no JavaScript rendering (browser_get does that), no sitemaps, no logins, no cookie jars,
no ignoring robots.txt, no crawling off the pages a workflow asked for.
"""
import collections
import re
import threading
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel, ConfigDict, Field

import research
import sandbox

MAX_PAGES = 40          # hard ceiling, whatever an agent asks for
MAX_DEPTH = 4
PAGE_TEXT = 4000        # characters of one page handed back to the model
TEXT_BUDGET = 24000     # characters of page text in one report, so a crawl cannot flood the window
MIN_DELAY = 1.0         # seconds between hits on one host
MAX_SECONDS = 300

_robots = {}            # host -> (RobotFileParser or None, crawl delay)
_last_hit = {}          # host -> when this process last fetched from it
_lock = threading.Lock()


class CrawlPage(BaseModel):
    """One page the crawler read."""
    model_config = ConfigDict(extra="forbid")

    url: str
    depth: int = 0
    from_url: str = ""
    title: str = ""
    words: int = 0
    text: str = ""
    note: str = ""
    error: str = ""


class CrawlReport(BaseModel):
    """What one crawl found, and why it stopped."""
    model_config = ConfigDict(extra="forbid")

    pages: list[CrawlPage] = Field(default_factory=list)
    start: str = ""
    read: int = 0            # pages fetched
    kept: int = 0            # pages that matched and came back
    stopped: str = ""        # the cap that fired: pages, depth, time, text, nothing left
    skipped: dict[str, int] = Field(default_factory=dict)
    frontier_left: int = 0
    seconds: float = 0


def _host(url):
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


def _site(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def _robots_for(url):
    """robots.txt for this host, fetched once per process. Unreachable robots means crawl allowed."""
    host = _host(url)
    with _lock:
        cached = _robots.get(host)
    if cached is None:
        parser, delay = None, MIN_DELAY
        try:
            answer = httpx.get(urljoin(host, "/robots.txt"), timeout=10, follow_redirects=True,
                               headers=research.HEADERS)
            if answer.status_code < 400 and answer.text.strip():
                parser = RobotFileParser()
                parser.parse(answer.text.splitlines())
                stated = parser.crawl_delay(research.HEADERS["User-Agent"]) or parser.crawl_delay("*")
                delay = max(MIN_DELAY, float(stated or 0))
        except Exception:
            parser = None
        cached = (parser, min(delay, 10.0))
        with _lock:
            _robots[host] = cached
    return cached


def _may_fetch(url):
    parser, delay = _robots_for(url)
    allowed = True if parser is None else parser.can_fetch(research.HEADERS["User-Agent"], url)
    return allowed, delay


def _be_polite(url, delay):
    """One host, one request at a time, spaced out. Crawling fast is how a workflow gets banned."""
    host = _host(url)
    with _lock:
        wait = delay - (time.monotonic() - _last_hit.get(host, 0))
        _last_hit[host] = time.monotonic() + max(0.0, wait)
    if wait > 0:
        time.sleep(min(wait, delay))


def crawl(start, pages=10, depth=2, same_site=True, must_match=""):
    """Walk a site from one page and hand back every page read, with the cap that stopped it."""
    report = CrawlReport(start=start)
    began = time.monotonic()
    pages = max(1, min(int(pages or 1), MAX_PAGES))
    depth = max(0, min(int(depth or 0), MAX_DEPTH))
    deadline = began + min(MAX_SECONDS, 30 + 12 * pages)
    try:
        wanted = re.compile(must_match, re.I) if must_match else None
    except re.error as e:
        report.stopped = f"must_match is not a regular expression: {e}"
        return report

    site = _site(start)
    queue = collections.deque([(start, 0, "")])
    queued = {research.key(start)}
    read_before = set(research.state()["pages"])  # page bodies this workflow read in an earlier run
    spent, held_back, report.stopped = 0, 0, "nothing left to follow"

    def skip(why):
        report.skipped[why] = report.skipped.get(why, 0) + 1

    while queue:
        if report.kept >= pages:
            report.stopped = f"page cap, {pages} pages"
            break
        if time.monotonic() > deadline:
            report.stopped = f"time cap, {int(time.monotonic() - began)}s"
            break
        url, step, parent = queue.popleft()
        refusal = sandbox.check_url(url)
        if refusal:
            skip("blocked by this workflow's network rules")
            continue
        allowed, delay = _may_fetch(url)
        if not allowed:
            skip("robots.txt says no")
            continue
        _be_polite(url, delay)
        try:
            answer = httpx.get(url, timeout=20, follow_redirects=True, headers=research.HEADERS)
            html = answer.text
            if answer.status_code >= 400:
                report.pages.append(CrawlPage(url=url, depth=step, from_url=parent,
                                              error=f"http {answer.status_code}"))
                skip(f"http {answer.status_code}")
                continue
        except Exception as e:
            report.pages.append(CrawlPage(url=url, depth=step, from_url=parent, error=str(e)[:200]))
            skip("could not be fetched")
            continue

        report.read += 1
        text = research.text_of(html)[:20000]
        digest = research.page_digest(text)
        stale = digest in read_before
        fresh = research.is_fresh_page(text)
        research.remember_page(url, text)

        links = research.links_in(html, url)
        research.note_links(links)
        onward = [l for l in links if not (same_site and _site(l) != site)]
        if step < depth:
            for link in onward:
                if research.key(link) in queued:
                    continue
                queued.add(research.key(link))
                queue.append((link, step + 1, url))
        else:
            held_back += len([l for l in onward if research.key(l) not in queued])

        if not fresh:
            skip("unchanged since an earlier run" if stale else "same page body under another url")
            continue
        if wanted and not wanted.search(url + " " + text):
            skip("did not match must_match")
            continue

        page = CrawlPage(url=url, depth=step, from_url=parent, title=research.title_of(html),
                         words=len(text.split()))
        room = TEXT_BUDGET - spent
        if room <= 0:
            page.note = "text budget spent, page stored for evidence only"
            report.stopped = "text budget"
        else:
            page.text = text[:min(PAGE_TEXT, room)]
            spent += len(page.text)
        report.pages.append(page)
        report.kept += 1

    if report.stopped == "nothing left to follow" and held_back:
        report.stopped = f"depth cap, {depth} link(s) deep, {held_back} link(s) left unfollowed"
    if not report.kept and report.skipped.get("unchanged since an earlier run"):
        report.stopped = ("every page read was unchanged since an earlier run, "
                          "nothing on this site is new")
    report.frontier_left = len(queue)
    report.seconds = round(time.monotonic() - began, 1)
    research._save()
    return report


def crawl_site(url: str, pages: int = 10, depth: int = 2, same_site: bool = True,
               must_match: str = "") -> str:
    """Crawl a site from one page, following its links, and return the text of every page read.

    Use this instead of fetching pages one at a time when the facts are spread over a whole site,
    such as a careers board, a docs set or a listings index. It obeys robots.txt and stops at the
    caps you give it. The report says which cap stopped it.

    Args:
        url: the page to start from
        pages: how many pages to return, at most 40
        depth: how many links deep to follow from the start page, at most 4
        same_site: true to stay on the starting site, false to follow links off it
        must_match: only return pages whose url or text matches this regular expression
    """
    refusal = sandbox.check_url(url)
    if refusal:
        return refusal
    report = crawl(url, pages=pages, depth=depth, same_site=same_site, must_match=must_match)
    return report.model_dump_json(indent=2)
