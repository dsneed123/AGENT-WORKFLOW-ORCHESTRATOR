import hashlib
import json
import os
import re
import threading

import httpx

import sandbox

HEADERS = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache", "Pragma": "no-cache"}
JUNK = re.compile(r"\.(css|js|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|zip|mp4|mp3)(\?|$)", re.I)
BLOCK = re.compile(
    r"doubleclick|googletagmanager|google-analytics|googlesyndication|adsystem|adservice|adnxs"
    r"|pub\.network|btloader|cookielaw|onetrust|quantserve|scorecardresearch|taboola|outbrain"
    r"|facebook\.com|twitter\.com|//x\.com|linkedin\.com|instagram\.com|pinterest\.|t\.co/"
    r"|youtube\.com|tiktok\.com|threads\.net|t\.me/|google\.com/preferences|uservoice|newsletters"
    r"|policies\.|/privacy|/terms|/cookie|/subscribe|/login|/signin|accounts\.", re.I)
CAP = 20000  # oldest entries fall off so a long-running crawler does not grow forever

STATES = {}            # workflow dir -> its crawl memory
_current = threading.local()


def use_dir(path):
    """Point crawl memory at a workflow's own folder. Call this in every thread that crawls."""
    _current.dir = path
    if path in STATES:
        return
    try:
        with open(os.path.join(path, "seen.json"), "r") as f:
            saved = json.load(f)
    except Exception:
        saved = {}
    STATES[path] = {
        "offered": dict.fromkeys(saved.get("offered", [])),   # handed to an agent by web_search
        "fetched": dict.fromkeys(saved.get("fetched", [])),   # already read by http_get
        "pages": dict.fromkeys(saved.get("pages", [])),       # content hashes already read
        "frontier": saved.get("frontier", []),                # links found on pages, not offered yet
        "text": {},                                           # url -> page text, this run only, for quote checks
    }


def state():
    path = getattr(_current, "dir", None)
    if path is None:
        path = os.path.dirname(os.path.abspath(__file__))
        use_dir(path)
    return STATES[path]


def _save():
    st = state()
    for key in ("offered", "fetched", "pages"):
        while len(st[key]) > CAP:
            st[key].pop(next(iter(st[key])))
    with open(os.path.join(_current.dir, "seen.json"), "w") as f:
        json.dump({"offered": list(st["offered"]), "fetched": list(st["fetched"]),
                   "pages": list(st["pages"]), "frontier": st["frontier"][:5000]}, f)


def fetched_text(url):
    """The text this workflow actually read off that page, or None if it never opened it."""
    return state()["text"].get(key(url))


def key(url):
    return re.sub(r"[?&](utm_[^&]*|fbclid|gclid)", "", url.lower()).replace("https://", "").replace(
        "http://", "").replace("www.", "").rstrip("/")


def _dom(url):
    return ".".join(key(url).split("/")[0].split(".")[-2:])


def _harvest(html):
    st = state()
    for url in re.findall(r'href="(https?://[^"\s#]+)"', html):
        if JUNK.search(url) or BLOCK.search(url):
            continue
        path = key(url).partition("/")[2].strip("/")
        if len(path) < 2:  # bare domains are usually ad hosts
            continue
        if path.count("/") < 2 and not re.search(r"/20\d\d/|-\w+-\w+-", "/" + path):
            continue  # keep article-shaped links, drop nav and profile pages
        if key(url) in st["offered"] or key(url) in st["fetched"]:
            continue
        if len(st["frontier"]) < 5000 and url not in st["frontier"]:
            st["frontier"].append(url)


def http_get(url: str) -> str:
    """Fetch a web page and return its visible text. Each page is only ever read once.

    Args:
        url: the full URL to fetch
    """
    refusal = sandbox.check_url(url)
    if refusal:
        return refusal
    st = state()
    if key(url) in st["fetched"]:
        return f"skipped, already read {url}, go somewhere new"
    try:
        html = httpx.get(url, timeout=15, follow_redirects=True, headers=HEADERS).text
    except Exception as e:
        return f"error {e}"
    st["fetched"][key(url)] = None
    _harvest(html)
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()[:20000]
    digest = hashlib.md5(text.encode()).hexdigest()
    if digest in st["pages"]:
        _save()
        return f"skipped, {url} repeats content already read, go somewhere new"
    st["pages"][digest] = None
    st["text"][key(url)] = text
    while len(st["text"]) > 60:  # evidence for recent pages only, text is heavy
        st["text"].pop(next(iter(st["text"])))
    _save()
    return text


def web_search(query: str) -> str:
    """Search the web for links never offered before. Falls back to crawling links found on pages already read.

    Args:
        query: what to search for
    """
    st = state()
    fresh = []
    for offset in (0, 30, 60, 90):  # page deeper when the first results were all offered already
        try:
            html = httpx.post("https://html.duckduckgo.com/html/",
                              data={"q": query, "s": offset, "dc": offset + 1},
                              timeout=15, follow_redirects=True, headers=HEADERS).text
        except Exception as e:
            return f"error {e}"
        hits = re.findall(r'result__a" href="([^"]+)"[^>]*>(.*?)</a>', html)
        if not hits:
            break
        for url, title in hits:
            if key(url) in st["offered"] or key(url) in st["fetched"]:
                continue
            st["offered"][key(url)] = None
            fresh.append(f"{re.sub(r'<[^>]+>', '', title)} - {url}")
            if len(fresh) >= 8:  # only burn links the agent actually gets to see
                break
        if len(fresh) >= 8:
            break

    hosts, i = set(), 0  # search dry, crawl onward, one link per domain so it spreads
    while i < len(st["frontier"]) and len(fresh) < 8:
        url = st["frontier"][i]
        if key(url) in st["offered"] or key(url) in st["fetched"]:
            st["frontier"].pop(i)
            continue
        if _dom(url) in hosts:
            i += 1
            continue
        st["frontier"].pop(i)
        hosts.add(_dom(url))
        st["offered"][key(url)] = None
        fresh.append(f"crawled link - {url}")

    _save()
    return "\n".join(fresh[:8]) or "nothing unseen left, fetch a page to find new links"
