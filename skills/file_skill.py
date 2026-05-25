import os
import subprocess
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from base_skill import BaseSkill
from core.logger import logger

VSCODE    = "Visual Studio Code"
DOWNLOADS = os.path.expanduser("~/Downloads")


def _run(args: list) -> None:
    subprocess.run(args, check=False)


def _open_path(path: str) -> None:
    _run(["open", os.path.expanduser(path)])


def _open_vscode(params: dict) -> str:
    _run(["open", "-a", VSCODE])
    return "VS Code opened."


def _open_vscode_path(params: dict) -> str:
    path = str(params.get("path", "")).strip()
    if not path:
        return "Please provide a path to open in VS Code."
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return f"Path not found: {expanded}"
    _run(["open", "-a", VSCODE, expanded])
    return f"Opened {expanded} in VS Code."


def _open_file(params: dict) -> str:
    path = str(params.get("path", "")).strip()
    if not path:
        return "Please provide a file path."
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return f"File not found: {expanded}"
    _open_path(expanded)
    return f"Opened {os.path.basename(expanded)}."


def _open_folder(params: dict) -> str:
    path = str(params.get("path", "")).strip()
    if not path:
        return "Please provide a folder path."
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return f"Folder not found: {expanded}"
    _open_path(expanded)
    return f"Opened folder {expanded}."


def _download_and_open(params: dict) -> str:
    url      = str(params.get("url", "")).strip()
    filename = str(params.get("filename", "")).strip()
    if not url:
        return "Please provide a URL to download."
    if not filename:
        filename = url.split("/")[-1].split("?")[0] or "download"

    dest = os.path.join(DOWNLOADS, filename)
    os.makedirs(DOWNLOADS, exist_ok=True)

    try:
        resp = requests.get(url, timeout=30, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
    except requests.exceptions.RequestException as e:
        return f"Download failed: {e}"

    _open_path(dest)
    return f"Downloaded and opened {filename}."


_ACTIONS = {
    "open_vscode":       _open_vscode,
    "open_vscode_path":  _open_vscode_path,
    "open_file":         _open_file,
    "open_folder":       _open_folder,
    "download_and_open": _download_and_open,
}


def _execute(params: dict) -> str:
    action = str(params.get("action", "")).strip()
    if not action:
        return "No file action specified."
    handler = _ACTIONS.get(action)
    if not handler:
        return f"Unknown file action: '{action}'. Available: {', '.join(_ACTIONS)}."
    try:
        return handler(params)
    except Exception as e:
        import traceback
        logger.error("Unexpected file error:\n%s", traceback.format_exc())
        return f"File error: {e}"


class FileSkill(BaseSkill):
    name        = "file"
    description = "File system and VS Code operations"

    def execute(self, params: dict) -> str:
        return _execute(params)


execute = FileSkill().execute
