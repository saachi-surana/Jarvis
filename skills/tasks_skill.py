import os
import sys
import sqlite3
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DB_PATH = os.path.expanduser("~/.notion-planner/tasks.db")


def _connect() -> sqlite3.Connection:
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _format_task(row: sqlite3.Row) -> str:
    text = row["text"]
    date_str = row["date"]
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %-d")
            return f"{text} (due {d})"
        except ValueError:
            pass
    return text


def _list_tasks(rows) -> str:
    if not rows:
        return None
    return "\n".join(f"  • {_format_task(r)}" for r in rows)


def execute(params: dict) -> str:
    action = str(params.get("action", "list")).strip().lower()

    try:
        conn = _connect()
    except FileNotFoundError:
        return (
            f"Tasks database not found at {DB_PATH}. "
            "Make sure the notion-planner project has been set up."
        )
    except Exception as e:
        return f"Couldn't open tasks database: {e}"

    try:
        with conn:
            if action == "list":
                return _do_list(conn)

            if action == "list_today":
                return _do_list_date(conn, date.today().isoformat())

            if action == "list_date":
                date_str = str(params.get("date", date.today().isoformat()))
                return _do_list_date(conn, date_str)

            if action == "add":
                return _do_add(conn, params)

            if action == "done":
                return _do_done(conn, params)

            if action == "list_done":
                return _do_list_done(conn)

            return f"Unknown tasks action '{action}'. Try: list, list_today, list_date, add, done, list_done."
    except Exception as e:
        return f"Tasks error: {e}"
    finally:
        conn.close()


def _do_list(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT * FROM tasks WHERE done = 0 ORDER BY sort_order ASC, created_at ASC"
    ).fetchall()
    formatted = _list_tasks(rows)
    if not formatted:
        return "No pending tasks — you're all clear."
    return f"Here are your pending tasks:\n{formatted}"


def _do_list_date(conn: sqlite3.Connection, date_str: str) -> str:
    rows = conn.execute(
        "SELECT * FROM tasks WHERE done = 0 AND date = ? ORDER BY sort_order ASC, created_at ASC",
        (date_str,),
    ).fetchall()
    formatted = _list_tasks(rows)
    if not formatted:
        try:
            label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d")
        except ValueError:
            label = date_str
        return f"No tasks scheduled for {label}."
    try:
        label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d")
    except ValueError:
        label = date_str
    return f"Tasks for {label}:\n{formatted}"


def _do_add(conn: sqlite3.Connection, params: dict) -> str:
    text = str(params.get("text", "")).strip()
    if not text:
        return "Please provide task text to add."
    date_str = params.get("date")
    if date_str:
        date_str = str(date_str).strip() or None
        if date_str and date_str.upper() == "TODAY":
            date_str = date.today().isoformat()
    created_at = datetime.now().isoformat(timespec="seconds")
    # Place new task at end of sort order
    max_order = conn.execute("SELECT MAX(sort_order) FROM tasks").fetchone()[0]
    sort_order = (max_order or 0) + 1
    conn.execute(
        "INSERT INTO tasks (text, done, date, created_at, sort_order) VALUES (?, 0, ?, ?, ?)",
        (text, date_str, created_at, sort_order),
    )
    if date_str:
        try:
            label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d")
        except ValueError:
            label = date_str
        return f"Added: \"{text}\" for {label}."
    return f"Added: \"{text}\"."


def _do_done(conn: sqlite3.Connection, params: dict) -> str:
    text = str(params.get("text", "")).strip()
    if not text:
        return "Please provide the task text to mark as done."
    rows = conn.execute(
        "SELECT id, text FROM tasks WHERE done = 0 AND text LIKE ?",
        (f"%{text}%",),
    ).fetchall()
    if not rows:
        return f"No pending task matching \"{text}\"."
    if len(rows) == 1:
        conn.execute("UPDATE tasks SET done = 1 WHERE id = ?", (rows[0]["id"],))
        return f"Marked done: \"{rows[0]['text']}\"."
    # Multiple matches — mark all and report
    ids = [r["id"] for r in rows]
    conn.execute(f"UPDATE tasks SET done = 1 WHERE id IN ({','.join('?' * len(ids))})", ids)
    titles = ", ".join(f"\"{r['text']}\"" for r in rows)
    return f"Marked {len(rows)} tasks done: {titles}."


def _do_list_done(conn: sqlite3.Connection) -> str:
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE done = 1 AND date(created_at) = ? ORDER BY created_at DESC",
        (today,),
    ).fetchall()
    formatted = _list_tasks(rows)
    if not formatted:
        return "No tasks completed today yet."
    return f"Completed today:\n{formatted}"
