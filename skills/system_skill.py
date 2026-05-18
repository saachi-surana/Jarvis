import os
import sys
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import WEATHER_CITY


def execute(params: dict) -> str:
    action = params.get("action", "")

    if action == "open_app":
        return _open_app(params.get("app", ""))

    if action == "search_web":
        return _search_web(params.get("query", ""))

    if action == "set_volume":
        return _set_volume(params.get("level", 5))

    if action == "get_time":
        return _get_time()

    if action == "get_weather":
        return _get_weather()

    if action == "run_command":
        return _run_command(params.get("command", ""))

    return f"Unknown system action: '{action}'"


def _open_app(app: str) -> str:
    if not app:
        return "No app name provided."
    try:
        subprocess.run(["open", "-a", app], check=True, capture_output=True)
        return f"Opening {app}."
    except subprocess.CalledProcessError:
        return f"Couldn't find an app named '{app}'."
    except Exception as e:
        return f"Failed to open {app}: {e}"


def _search_web(query: str) -> str:
    if not query:
        return "No search query provided."
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    webbrowser.open(url)
    return f"Opened a Google search for '{query}'."


def _set_volume(level) -> str:
    try:
        level = int(level)
    except (TypeError, ValueError):
        return "Volume level must be a number between 0 and 10."
    level = max(0, min(10, level))
    try:
        subprocess.run(
            ["osascript", "-e", f"set volume {level}"],
            check=True,
            capture_output=True,
        )
        return f"Volume set to {level}."
    except Exception as e:
        return f"Couldn't set volume: {e}"


def _get_time() -> str:
    now = datetime.now()
    hour = now.strftime("%I").lstrip("0") or "12"
    minute = now.strftime("%M")
    period = now.strftime("%p")
    day = now.strftime("%A, %B %-d")
    return f"It's {hour}:{minute} {period} on {day}."


def _get_weather() -> str:
    try:
        resp = requests.get(
            f"https://wttr.in/{urllib.parse.quote_plus(WEATHER_CITY)}",
            params={"format": "3"},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.text.strip()
    except requests.exceptions.Timeout:
        return "Weather request timed out. Try again in a moment."
    except Exception as e:
        return f"Couldn't fetch weather: {e}"


def _run_command(command: str) -> str:
    if not command:
        return "No command provided."
    print(f"\n[System] About to run: {command}")
    try:
        confirm = input("Run this command? (yes/no): ").strip().lower()
    except EOFError:
        return "Cannot confirm command — no interactive terminal available."
    if confirm not in ("yes", "y"):
        return "Command cancelled."
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            return "Command ran with no output."
        if len(output) > 500:
            output = output[:500] + "… (truncated)"
        return output
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Command failed: {e}"
