import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from base_skill import BaseSkill
from config import STUDYSYNC_URL

_NOT_RUNNING = "StudySync isn't running. Start it and try again."
_DOWNLOADS   = os.path.expanduser("~/Downloads/StudySync")


def _get(path: str, params: dict = None) -> requests.Response:
    return requests.get(f"{STUDYSYNC_URL}{path}", params=params, timeout=10)


def _post(path: str, payload: dict) -> requests.Response:
    return requests.post(f"{STUDYSYNC_URL}{path}", json=payload, timeout=30)


def _connection_error(e: Exception) -> bool:
    return isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def _list_courses() -> str:
    resp = _get("/courses")
    resp.raise_for_status()
    courses = resp.json()
    if not courses:
        return "No courses found in StudySync."
    names = [c["name"] for c in courses]
    return "Your courses: " + ", ".join(names) + "."


def _list_lectures(course_filter: str) -> str:
    lectures_resp = _get("/lectures")
    lectures_resp.raise_for_status()
    lectures = lectures_resp.json()

    if not lectures:
        return "No lectures found in StudySync."

    if course_filter:
        courses_resp = _get("/courses")
        courses_resp.raise_for_status()
        id_to_name = {c["id"]: c["name"] for c in courses_resp.json()}
        lectures = [
            l for l in lectures
            if id_to_name.get(l["course_id"], "").lower() == course_filter.lower()
        ]
        if not lectures:
            return f"No lectures found for course '{course_filter}'."
        header = f"Lectures for {course_filter}:"
    else:
        header = "All lectures:"

    titles = [f"  • {l['title']}" for l in lectures]
    return header + "\n" + "\n".join(titles)


def _search(query: str, course: str = None) -> str:
    if not query:
        return "Please provide a search query."
    params = {"q": query}
    if course:
        params["course"] = course
    resp = _get("/search", params=params)
    resp.raise_for_status()
    results = resp.json()

    if not results:
        msg = f"No results for '{query}'"
        msg += f" in {course}." if course else "."
        return msg

    lines = []
    for r in results:
        lines.append(f"  [{r['course']}] {r['title']}")
        if r.get("excerpt"):
            lines.append(f"    {r['excerpt']}")
    header = f"{len(results)} result{'s' if len(results) != 1 else ''} for '{query}':"
    return header + "\n" + "\n".join(lines)


def _generate(lecture_title: str, kind: str) -> str:
    if not lecture_title:
        return f"Please provide a lecture title to generate a {kind} for."

    resp = _get("/lectures")
    resp.raise_for_status()
    lectures = resp.json()

    match = _fuzzy_find(lecture_title, lectures, key="title")
    if match is None:
        return f"Couldn't find a lecture matching '{lecture_title}'."

    course_id     = match["course_id"]
    matched_title = match["title"]

    endpoint = "/cheatsheet/generate" if kind == "cheatsheet" else "/quiz/generate"
    gen_resp  = _post(endpoint, {"course_id": course_id})

    if gen_resp.status_code == 400:
        detail = gen_resp.json().get("detail", "Unknown error")
        return f"Couldn't generate {kind}: {detail}"
    gen_resp.raise_for_status()
    data = gen_resp.json()

    if kind == "cheatsheet":
        content = data.get("content", "")
        if not content:
            return "Cheatsheet generated but returned empty content."
        preview = content[:600]
        if len(content) > 600:
            preview += "\n... (truncated — full cheatsheet available in StudySync)"
        return f"Cheatsheet for '{matched_title}':\n{preview}"

    questions = data.get("questions", [])
    count = len(questions)
    if not questions:
        return "Quiz generated but returned no questions."
    return (
        f"Generated a {count}-question quiz for the course covering '{matched_title}'. "
        "Open StudySync to take it."
    )


def _download_lecture(lecture_title: str) -> str:
    if not lecture_title:
        return "Please provide a lecture title to download."

    lectures_resp = _get("/lectures")
    lectures_resp.raise_for_status()
    lectures = lectures_resp.json()

    courses_resp = _get("/courses")
    courses_resp.raise_for_status()
    id_to_name = {c["id"]: c["name"] for c in courses_resp.json()}

    match = _fuzzy_find(lecture_title, lectures, key="title")
    if match is None:
        return f"Couldn't find a lecture matching '{lecture_title}'."

    matched_title = match["title"]
    course_name   = id_to_name.get(match.get("course_id"), "Unknown Course")

    file_url = (
        match.get("file_url")
        or match.get("slides_url")
        or match.get("pdf_url")
        or match.get("url")
    )

    if not file_url or not str(file_url).startswith("http"):
        return f"No files available for '{matched_title}'."

    safe_course = _safe_name(course_name)
    safe_title  = _safe_name(matched_title)
    dest_dir    = os.path.join(_DOWNLOADS, safe_course)
    os.makedirs(dest_dir, exist_ok=True)

    url_path = file_url.split("?")[0]
    ext      = os.path.splitext(url_path)[1] or ".pdf"
    dest     = os.path.join(dest_dir, safe_title + ext)

    try:
        resp = requests.get(file_url, timeout=60, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
    except requests.exceptions.RequestException as e:
        return f"Download failed: {e}"

    subprocess.run(["open", dest], check=False)
    return f"Downloaded and opened '{matched_title}' ({safe_title}{ext}) — saved to {dest}."


def _fuzzy_find(query: str, items: list, key: str):
    lower_q = query.lower()
    for item in items:
        if item.get(key, "").lower() == lower_q:
            return item
    for item in items:
        if lower_q in item.get(key, "").lower():
            return item
    return None


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in name).strip()


def _execute(params: dict) -> str:
    action = str(params.get("action", "")).strip().lower()

    try:
        if action == "list_courses":
            return _list_courses()
        if action == "list_lectures":
            return _list_lectures(params.get("course", ""))
        if action == "search":
            return _search(params.get("query", ""), params.get("course"))
        if action == "cheatsheet":
            return _generate(params.get("lecture_title", ""), "cheatsheet")
        if action == "quiz":
            return _generate(params.get("lecture_title", ""), "quiz")
        if action == "download_lecture":
            return _download_lecture(params.get("lecture_title", ""))
        return (
            f"Unknown StudySync action '{action}'. "
            "Try: list_courses, list_lectures, search, cheatsheet, quiz, download_lecture."
        )
    except requests.exceptions.ConnectionError:
        return _NOT_RUNNING
    except requests.exceptions.Timeout:
        return "StudySync took too long to respond. Try again."
    except Exception as e:
        return f"StudySync error: {e}"


class StudySyncSkill(BaseSkill):
    name        = "studysync"
    description = "StudySync course, lecture, and content management"

    def execute(self, params: dict) -> str:
        return _execute(params)


execute = StudySyncSkill().execute
