import os
import subprocess
import sys
import time
from urllib.parse import quote_plus

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from base_skill import BaseSkill
from core.logger import logger
from config import STUDYSYNC_URL

BRAVE = "Brave Browser"

_SKIP_DOMAINS  = {"reddit.com", "quora.com", "pinterest.com", "medium.com"}
_SCORE_3       = {"arxiv.org", "scholar.google.com"}
_SCORE_2       = {"wikipedia.org", "github.com", "youtube.com"}
_DOCS_PATTERNS = ("docs.", "/docs", "documentation", "readthedocs")


def _open_in_brave(url: str) -> None:
    subprocess.Popen(["open", "-a", BRAVE, url])
    time.sleep(0.2)


def _open_in_new_brave_window(url: str) -> None:
    subprocess.run(
        ["open", "-na", BRAVE, "--args", "--new-window", url],
        check=False,
    )
    time.sleep(0.3)


def _ensure_brave_running() -> None:
    subprocess.Popen(["open", "-a", BRAVE])
    time.sleep(1)


def _score_url(url: str) -> int:
    lower = url.lower()
    for skip in _SKIP_DOMAINS:
        if skip in lower:
            return 0
    for d in _SCORE_3:
        if d in lower:
            return 3
    if ".edu" in lower:
        return 3
    for d in _SCORE_2:
        if d in lower:
            return 2
    for p in _DOCS_PATTERNS:
        if p in lower:
            return 2
    return 1


def _open_tabs(params: dict) -> str:
    urls = params.get("urls", [])
    if not urls:
        return "No URLs provided."
    if isinstance(urls, str):
        urls = [u.strip() for u in urls.split(",") if u.strip()]
    _ensure_brave_running()
    for url in urls:
        if not url.startswith("http"):
            url = "https://" + url
        _open_in_brave(url)
    count = len(urls)
    return f"Opened {count} tab{'s' if count != 1 else ''} in Brave."


def _study_mode(params: dict) -> str:
    course = str(params.get("course", "")).strip()
    if not course:
        return "Please specify a course for study mode."

    _ensure_brave_running()
    urls_opened = []

    try:
        import requests
        resp = requests.get(f"{STUDYSYNC_URL}/lectures", params={"course": course}, timeout=5)
        if resp.ok:
            for lec in resp.json()[:4]:
                url = lec.get("url") or lec.get("link", "")
                if url and url.startswith("http"):
                    _open_in_brave(url)
                    urls_opened.append(url)
    except Exception as e:
        logger.error("StudySync fetch failed in study_mode: %s", e)

    ddg_url = f"https://duckduckgo.com/?q={quote_plus(course)}"
    _open_in_brave(ddg_url)
    urls_opened.append(ddg_url)

    return f"Study mode: opened {len(urls_opened)} resource{'s' if len(urls_opened) != 1 else ''} for {course}."


def _research_mode(params: dict) -> str:
    topic = str(params.get("query", "")).strip()
    if not topic:
        return "Please provide a research topic."

    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(topic, max_results=10))
    except Exception as e:
        return f"Search failed: {e}"

    scored   = sorted(
        [(r, _score_url(r.get("href", ""))) for r in raw if r.get("href")],
        key=lambda x: x[1],
        reverse=True,
    )
    top_urls = [r["href"] for r, s in scored if s > 0][:4]
    yt_url   = f"https://www.youtube.com/results?search_query={quote_plus(topic)}"
    all_urls = top_urls + [yt_url]

    _ensure_brave_running()
    for url in all_urls:
        _open_in_brave(url)

    def _hostname(url: str) -> str:
        try:
            from urllib.parse import urlparse
            h = urlparse(url).hostname or url
            return h.removeprefix("www.")
        except Exception:
            return url

    site_names = ", ".join(_hostname(u) for u in all_urls)
    return f"Opening {len(all_urls)} sources on {topic}: {site_names}."


def _coding_mode(params: dict) -> str:
    query = str(params.get("query", "")).strip()

    try:
        subprocess.Popen(["open", "-a", "Visual Studio Code"])
    except Exception:
        try:
            subprocess.Popen(["code", "."])
        except Exception:
            pass

    _ensure_brave_running()
    urls_opened = []

    if query:
        gh_url  = f"https://github.com/search?q={quote_plus(query)}&type=repositories"
        doc_url = f"https://duckduckgo.com/?q={quote_plus(query)}+documentation"
        _open_in_brave(gh_url)
        _open_in_brave(doc_url)
        urls_opened = [gh_url, doc_url]

    return "Coding mode: VS Code opened" + (
        f", {len(urls_opened)} browser tabs for '{query}'." if query else "."
    )


def _deep_research(params: dict) -> str:
    topic = str(params.get("query", "")).strip()
    if not topic:
        return "Please provide a research topic."

    enc  = quote_plus(topic)
    urls = [
        f"https://arxiv.org/search/?searchtype=all&query={enc}",
        f"https://github.com/search?q={enc}&type=repositories",
    ]

    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(topic, max_results=10))
        ddg_picks = [
            r["href"] for r in raw
            if r.get("href") and _score_url(r["href"]) > 0
        ][:3]
        urls.extend(ddg_picks)
    except Exception as e:
        logger.error("DDG failed in deep_research: %s", e)

    if urls:
        _open_in_new_brave_window(urls[0])
        time.sleep(0.8)
        for url in urls[1:]:
            _open_in_brave(url)

    return f"Deep research mode activated for {topic}."


_ACTIONS = {
    "open_tabs":     _open_tabs,
    "study_mode":    _study_mode,
    "research_mode": _research_mode,
    "coding_mode":   _coding_mode,
    "deep_research": _deep_research,
}


def _execute(params: dict) -> str:
    action = str(params.get("action", "")).strip()
    if not action:
        return "No browser action specified."
    handler = _ACTIONS.get(action)
    if not handler:
        return f"Unknown browser action: '{action}'. Available: {', '.join(_ACTIONS)}."
    try:
        return handler(params)
    except Exception as e:
        import traceback
        logger.error("Unexpected browser error:\n%s", traceback.format_exc())
        return f"Browser error: {e}"


class BrowserSkill(BaseSkill):
    name        = "browser"
    description = "Brave Browser automation: tabs, study/research/coding modes"

    def execute(self, params: dict) -> str:
        return _execute(params)


execute = BrowserSkill().execute
