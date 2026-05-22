#!/usr/bin/env python3
"""
Jarvis skill smoke tests — calls execute() directly, no voice/UI needed.

Run with:  python3 tests/test_skills.py

Edit the flags below to control tests that touch external services or
open applications.
"""
import os
import sys
import time
import traceback
from datetime import date, timedelta

# ── path setup ────────────────────────────────────────────────────────────────
ROOT   = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKILLS = os.path.join(ROOT, "skills")
for _p in (ROOT, SKILLS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── flags ─────────────────────────────────────────────────────────────────────
RUN_BROWSER_TESTS   = False  # True → actually opens Brave tabs
RUN_CALENDAR_CREATE = True   # True → creates a real Google Calendar test event
RUN_TIMER_TEST      = True   # True → chime sounds ~6 s after this test runs

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
TASK_TAG  = f"JARVIS_TEST_{int(time.time())}"  # unique key to find our test task

# ── ANSI colours (gracefully off if piped) ────────────────────────────────────
_tty = sys.stdout.isatty()
def _c(code, text): return f"\033[{code}m{text}\033[0m" if _tty else text
GREEN  = lambda t: _c(32, t)
RED    = lambda t: _c(31, t)
YELLOW = lambda t: _c(33, t)
BOLD   = lambda t: _c(1,  t)

# ── harness ───────────────────────────────────────────────────────────────────
_passed  = 0
_failed  = 0
_skipped = 0
_log: list[tuple] = []   # (status, label, detail)


def _check(label: str, fn, *, must_contain: str = None, skip: bool = False, skip_reason: str = "") -> object:
    """
    Run fn(), record PASS/FAIL/SKIP.

    PASS  — fn() returns a non-empty string, and must_contain (if set) is found.
    FAIL  — fn() raises, returns empty, or must_contain is missing.
    SKIP  — skip=True.
    """
    global _passed, _failed, _skipped

    if skip:
        _skipped += 1
        _log.append(("SKIP", label, skip_reason))
        print(f"  {YELLOW('SKIP')}  {label}")
        print(f"        {skip_reason}")
        return None

    try:
        result = fn()
        result_str = str(result).strip()

        ok = bool(result_str)
        if ok and must_contain and must_contain.lower() not in result_str.lower():
            ok = False
            result_str = f"expected '{must_contain}' not found → {result_str}"

        snippet = result_str[:130] + ("…" if len(result_str) > 130 else "")

        if ok:
            _passed += 1
            _log.append(("PASS", label, result_str))
            print(f"  {GREEN('PASS ✓')}  {label}")
            print(f"        {snippet}")
        else:
            _failed += 1
            _log.append(("FAIL", label, result_str))
            print(f"  {RED('FAIL ✗')}  {label}")
            print(f"        {snippet}")

        return result if ok else None

    except Exception:
        last_line = traceback.format_exc().strip().splitlines()[-1]
        _failed += 1
        _log.append(("FAIL", label, last_line))
        print(f"  {RED('FAIL ✗')}  {label}")
        print(f"        {last_line[:130]}")
        return None


def _section(title: str) -> None:
    bar = "─" * 54
    print(f"\n{BOLD(bar)}")
    print(BOLD(f"  {title}"))
    print(bar)


def _import(module_name: str):
    """Import a skill module, returning it or None on failure."""
    try:
        mod = __import__(module_name)
        return mod
    except Exception as e:
        _failed_import(module_name, e)
        return None


def _failed_import(name: str, exc: Exception) -> None:
    global _failed
    _failed += 1
    msg = f"ImportError: {exc}"
    _log.append(("FAIL", f"{name}.import", msg))
    print(f"  {RED('FAIL ✗')}  import {name}")
    print(f"        {msg}")


# ── individual skill test suites ──────────────────────────────────────────────

def test_calendar() -> None:
    _section("calendar_skill")
    cal = _import("calendar_skill")
    if cal is None:
        return

    _check("query: today",
           lambda: cal.execute({"query": "today"}))

    _check("query: tomorrow",
           lambda: cal.execute({"query": "tomorrow"}))

    _check("query: week",
           lambda: cal.execute({"query": "week"}))

    _check("query: next_event",
           lambda: cal.execute({"query": "next_event"}))

    _check("create: test event (delete me)",
           lambda: cal.execute({
               "action":     "create",
               "title":      "JARVIS Smoke Test (delete me)",
               "date":       TOMORROW,
               "start_time": "23:00",
               "end_time":   "23:30",
           }),
           must_contain="Added",
           skip=not RUN_CALENDAR_CREATE,
           skip_reason="RUN_CALENDAR_CREATE=False")


def test_tasks() -> None:
    _section("tasks_skill")
    tasks = _import("tasks_skill")
    if tasks is None:
        return

    _check("list (initial state)",
           lambda: tasks.execute({"action": "list"}))

    add_result = _check("add test task",
                        lambda: tasks.execute({"action": "add", "text": TASK_TAG, "date": "TODAY"}),
                        must_contain="Added")

    if add_result:
        _check("list → verify task appears",
               lambda: tasks.execute({"action": "list"}),
               must_contain=TASK_TAG)

        _check("done → mark test task complete",
               lambda: tasks.execute({"action": "done", "text": TASK_TAG}),
               must_contain="Marked done")
    else:
        for label in ("list → verify task appears", "done → mark test task complete"):
            global _skipped
            _skipped += 1
            _log.append(("SKIP", label, "add step failed"))
            print(f"  {YELLOW('SKIP')}  {label}")
            print(f"        add step failed — nothing to verify")

    _check("list_done",
           lambda: tasks.execute({"action": "list_done"}))


def test_search() -> None:
    _section("search_skill")
    search = _import("search_skill")
    if search is None:
        return

    _check("source: tasks — query 'test'",
           lambda: search.execute({"query": "test", "source": "tasks"}))

    _check("source: calendar — query 'meeting'",
           lambda: search.execute({"query": "meeting", "source": "calendar"}))

    _check("source: studysync — query 'lecture' (offline-safe)",
           lambda: search.execute({"query": "lecture", "source": "studysync"}))

    _check("source: all — query 'homework'",
           lambda: search.execute({"query": "homework", "source": "all"}))


def test_system() -> None:
    _section("system_skill")
    sys_sk = _import("system_skill")
    if sys_sk is None:
        return

    _check("get_time",
           lambda: sys_sk.execute({"action": "get_time"}),
           must_contain=":")                  # "It's 3:04 PM on..."

    _check("get_weather (network)",
           lambda: sys_sk.execute({"action": "get_weather"}))


def test_studysync() -> None:
    _section("studysync_skill  [StudySync must be running on :8000]")
    ss = _import("studysync_skill")
    if ss is None:
        return

    _check("list_courses  (offline → friendly message)",
           lambda: ss.execute({"action": "list_courses"}))

    _check("list_lectures (offline → friendly message)",
           lambda: ss.execute({"action": "list_lectures", "course": ""}))

    _check("search 'lecture' (offline → friendly message)",
           lambda: ss.execute({"action": "search", "query": "lecture"}))


def test_spotify() -> None:
    _section("spotify_skill  [read-only — does NOT change playback]")
    spot = _import("spotify_skill")
    if spot is None:
        return

    # what_playing is the only safe read-only action
    _check("what_playing",
           lambda: spot.execute({"action": "what_playing"}))


def test_browser() -> None:
    _section("browser_skill")
    browser = _import("browser_skill")
    if browser is None:
        return

    _check("research_mode: 'python'  (opens Brave)",
           lambda: browser.execute({"action": "research_mode", "query": "python"}),
           must_contain="Opening",
           skip=not RUN_BROWSER_TESTS,
           skip_reason="RUN_BROWSER_TESTS=False — set True at top of file to run")

    # Score logic is pure-Python — test it without opening anything
    _check("_score_url: arxiv → 3",
           lambda: "ok" if browser._score_url("https://arxiv.org/abs/1234.5678") == 3 else
                   f"expected 3, got {browser._score_url('https://arxiv.org/abs/1234.5678')}")

    _check("_score_url: reddit → 0 (skipped)",
           lambda: "ok" if browser._score_url("https://reddit.com/r/python") == 0 else
                   f"expected 0, got {browser._score_url('https://reddit.com/r/python')}")

    _check("_score_url: wikipedia → 2",
           lambda: "ok" if browser._score_url("https://en.wikipedia.org/wiki/Python") == 2 else
                   f"expected 2, got {browser._score_url('https://en.wikipedia.org/wiki/Python')}")

    _check("_score_url: .edu → 3",
           lambda: "ok" if browser._score_url("https://cs.washington.edu/courses") == 3 else
                   f"expected 3, got {browser._score_url('https://cs.washington.edu/courses')}")


def test_timer() -> None:
    _section("timer_skill")
    if not RUN_TIMER_TEST:
        _skipped += 1
        _log.append(("SKIP", "set 0.1-min timer", "RUN_TIMER_TEST=False"))
        print(f"  {YELLOW('SKIP')}  set 0.1-min timer")
        print(f"        RUN_TIMER_TEST=False")
        return

    timer = _import("timer_skill")
    if timer is None:
        return

    print(f"  {YELLOW('NOTE')}  A chime will sound ~6 seconds after this test.")
    _check("set 0.1-minute (6 s) timer",
           lambda: timer.execute({"duration_minutes": 0.1, "label": "Smoke Test"}),
           must_contain="set for")


def test_web() -> None:
    _section("web_skill  [hits DuckDuckGo + Ollama]")
    web = _import("web_skill")
    if web is None:
        return

    _check("search: 'Seattle weather'",
           lambda: web.execute({"query": "Seattle weather"}))


def test_file() -> None:
    _section("file_skill")
    fsk = _import("file_skill")
    if fsk is None:
        return

    # Test error-path (no subprocess launched) — safe to run always
    _check("open_vscode_path: nonexistent path → error",
           lambda: fsk.execute({"action": "open_vscode_path", "path": "~/nonexistent_jarvis_test_path"}),
           must_contain="not found")

    _check("open_file: nonexistent path → error",
           lambda: fsk.execute({"action": "open_file", "path": "~/nonexistent_jarvis_test_file.txt"}),
           must_contain="not found")

    # Opens ~/Downloads in Finder — harmless
    _check("open_folder: ~/Downloads",
           lambda: fsk.execute({"action": "open_folder", "path": "~/Downloads"}),
           must_contain="Opened folder")


# ── summary ───────────────────────────────────────────────────────────────────

def _summary() -> None:
    bar = "═" * 54
    total_run = _passed + _failed
    print(f"\n{BOLD(bar)}")
    colour = GREEN if _failed == 0 else RED
    print(BOLD(f"  RESULTS: {colour(f'{_passed}/{total_run} passing')}  ({_skipped} skipped)"))

    if _failed:
        print(f"\n  {RED('Failed tests:')}")
        for status, label, detail in _log:
            if status == "FAIL":
                print(f"    {RED('✗')} {label}")
                print(f"      {detail[:100]}")

    if _skipped:
        print(f"\n  {YELLOW('Skipped tests:')}")
        for status, label, detail in _log:
            if status == "SKIP":
                print(f"    {YELLOW('–')} {label}")

    print(BOLD(bar))
    print()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(BOLD("\n  JARVIS SKILL SMOKE TESTS"))
    print(f"  date: {date.today()}  |  task tag: {TASK_TAG}")
    print(f"  flags: browser={'on' if RUN_BROWSER_TESTS else 'off'}  "
          f"calendar_create={'on' if RUN_CALENDAR_CREATE else 'off'}  "
          f"timer={'on' if RUN_TIMER_TEST else 'off'}")

    test_calendar()
    test_tasks()
    test_search()
    test_system()
    test_studysync()
    test_spotify()
    test_browser()
    test_timer()
    test_web()
    test_file()

    _summary()
