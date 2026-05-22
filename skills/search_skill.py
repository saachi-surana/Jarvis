import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DB_PATH = os.path.expanduser("~/.notion-planner/tasks.db")


# ── helpers ───────────────────────────────────────────────────────────────────

def _search_tasks(query: str) -> list[str]:
    if not os.path.isfile(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        pattern = f"%{query}%"
        rows = conn.execute(
            "SELECT text, date FROM tasks WHERE done=0 AND text LIKE ? ORDER BY date, sort_order LIMIT 10",
            (pattern,),
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            date_str = f" ({r['date']})" if r["date"] else ""
            results.append(f"{r['text']}{date_str}")
        return results
    except Exception as e:
        print(f"[Search] tasks error: {e}")
        return []


def _search_calendar(query: str) -> list[str]:
    try:
        from calendar_skill import _build_service, _fetch_events
        service = _build_service()
        now      = datetime.now(timezone.utc)
        events   = _fetch_events(service, now, now + timedelta(days=30))
        q = query.lower()
        results = []
        for ev in events:
            summary = ev.get("summary", "")
            desc    = ev.get("description", "")
            if q in summary.lower() or q in desc.lower():
                start = ev.get("start", {})
                dt_str = start.get("dateTime") or start.get("date", "")
                # Format nicely: "2026-05-22T14:00:00-07:00" → "2026-05-22 14:00"
                try:
                    dt = datetime.fromisoformat(dt_str)
                    dt_str = dt.strftime("%b %d %I:%M %p").lstrip("0")
                except Exception:
                    pass
                results.append(f"{summary} — {dt_str}")
        return results[:5]
    except Exception as e:
        print(f"[Search] calendar error: {e}")
        return []


def _search_studysync(query: str) -> list[str]:
    try:
        from config import STUDYSYNC_URL
        resp = requests.get(f"{STUDYSYNC_URL}/search", params={"q": query}, timeout=5)
        if not resp.ok:
            return []
        data = resp.json()
        # Expect list of {title, course, ...} or plain strings
        results = []
        for item in data[:5]:
            if isinstance(item, dict):
                title  = item.get("title") or item.get("name", "")
                course = item.get("course", "")
                entry  = f"{title} [{course}]" if course else title
                if entry.strip():
                    results.append(entry.strip())
            elif isinstance(item, str) and item:
                results.append(item)
        return results
    except Exception as e:
        print(f"[Search] studysync error: {e}")
        return []


# ── dispatch ─────────────────────────────────────────────────────────────────

def execute(params: dict) -> str:
    query = str(params.get("query", "")).strip()
    if not query:
        return "Please provide a search query."

    source = str(params.get("source", "all")).strip().lower()

    sections = []

    if source in ("all", "tasks"):
        hits = _search_tasks(query)
        if hits:
            sections.append("TASKS:\n" + "\n".join(f"  • {h}" for h in hits))
        elif source == "tasks":
            sections.append("TASKS: No matching tasks found.")

    if source in ("all", "calendar"):
        hits = _search_calendar(query)
        if hits:
            sections.append("CALENDAR:\n" + "\n".join(f"  • {h}" for h in hits))
        elif source == "calendar":
            sections.append("CALENDAR: No matching events in the next 30 days.")

    if source in ("all", "studysync"):
        hits = _search_studysync(query)
        if hits:
            sections.append("STUDYSYNC:\n" + "\n".join(f"  • {h}" for h in hits))
        elif source == "studysync":
            sections.append("STUDYSYNC: No results (service may be offline).")

    if not sections:
        return f"No results found for '{query}'."

    return "\n\n".join(sections)
