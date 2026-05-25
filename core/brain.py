import sys
import os
from typing import Optional, Union

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import OLLAMA_MODEL, OLLAMA_URL, MAX_HISTORY
from core.logger import logger
import ollama

SYSTEM_PROMPT = (
    "You are Jarvis, a highly intelligent AI assistant for Saachi (pronounced SAH-chee) — "
    "inspired by Jarvis from Iron Man. "
    "You are concise, witty, and speak with calm confidence. "
    "Keep responses under 3 sentences unless asked for more.\n\n"
    "Use the available tools whenever a request requires action. "
    "For general conversation or questions you can answer directly, respond in plain text only.\n\n"
    "KEY ROUTING RULES:\n"
    "- Any request involving music, songs, artists, play/pause/skip, or audio playback → spotify tool. "
    "  Exception: 'open Spotify' the app → system tool.\n"
    "- If the message is just an artist name, song name, or '[song] by [artist]' with no other words, "
    "  treat it as a Spotify play request.\n"
    "- Calendar reads: set query to 'today', 'tomorrow', 'week', or 'next_event'.\n"
    "- Calendar creates: set action to 'create' with title, date (YYYY-MM-DD), "
    "  start_time and end_time (HH:MM 24-hour).\n"
    "- Task adds: use date='TODAY' if the task is for today, otherwise YYYY-MM-DD.\n"
    "- NEVER fabricate URLs — only use URLs explicitly provided by the user."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calendar",
            "description": (
                "Read or create Google Calendar events. "
                "To read: set query to 'today', 'tomorrow', 'week', or 'next_event'. "
                "To create: set action to 'create' and provide title, date (YYYY-MM-DD), "
                "start_time and end_time (HH:MM 24-hour format)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create"],
                        "description": "Set to 'create' when adding a new event",
                    },
                    "query": {
                        "type": "string",
                        "enum": ["today", "tomorrow", "week", "next_event"],
                        "description": "Which events to fetch (read operations only)",
                    },
                    "title":      {"type": "string"},
                    "date":       {"type": "string", "description": "YYYY-MM-DD"},
                    "start_time": {"type": "string", "description": "HH:MM 24-hour"},
                    "end_time":   {"type": "string", "description": "HH:MM 24-hour"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify",
            "description": "Control Spotify playback — play, pause, skip, search songs and artists, set volume",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "play", "pause", "next", "previous",
                            "play_song", "play_artist", "what_playing", "volume",
                        ],
                    },
                    "query": {
                        "type": "string",
                        "description": "Song or artist name for play_song / play_artist",
                    },
                    "level": {
                        "type": "integer",
                        "description": "Volume level 0–100 (volume action only)",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tasks",
            "description": "Manage tasks in the local task database — list, add, or mark done",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "list_today", "add", "done", "list_done"],
                    },
                    "text": {"type": "string", "description": "Task description for add or done"},
                    "date": {
                        "type": "string",
                        "description": "Use 'TODAY' for today's date, or YYYY-MM-DD for a specific date",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system",
            "description": "Control Mac system — open non-music apps, get current time",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open_app", "get_time"],
                    },
                    "app": {"type": "string", "description": "App name for open_app"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser",
            "description": "Control Brave browser — open URLs, or enter study, research, coding, or deep-research mode",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "open_tabs", "study_mode",
                            "research_mode", "coding_mode", "deep_research",
                        ],
                    },
                    "query":  {
                        "type": "string",
                        "description": "Search topic for research_mode, coding_mode, deep_research",
                    },
                    "course": {
                        "type": "string",
                        "description": "Course name for study_mode",
                    },
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs to open for open_tabs",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "timer",
            "description": "Set a countdown timer with an optional label",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {"type": "number"},
                    "label":            {"type": "string"},
                },
                "required": ["duration_minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search across tasks, calendar, and StudySync",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["all", "tasks", "calendar", "studysync"],
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "studysync",
            "description": "Access StudySync courses and lecture materials",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "list_courses", "list_lectures", "search",
                            "cheatsheet", "quiz", "download_lecture",
                        ],
                    },
                    "course":        {"type": "string"},
                    "query":         {"type": "string"},
                    "lecture_title": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web",
            "description": "Search the web via DuckDuckGo",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file",
            "description": "Open files, folders, or VS Code",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "open_vscode", "open_vscode_path",
                            "open_file", "open_folder", "download_and_open",
                        ],
                    },
                    "path":     {"type": "string"},
                    "url":      {"type": "string"},
                    "filename": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
]


class Brain:
    def __init__(self):
        self._history: list[dict] = []
        self._client = ollama.Client(host=OLLAMA_URL)

    def think(self, user_input: str) -> Optional[Union[str, dict]]:
        self._history.append({"role": "user", "content": user_input})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._history

        try:
            response = self._client.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=TOOLS,
            )

            if response.message.tool_calls:
                tool_call = response.message.tool_calls[0]
                result: Union[str, dict] = {
                    "action": tool_call.function.name,
                    "params": dict(tool_call.function.arguments),
                }
                self._history.append({"role": "assistant", "content": ""})
            else:
                reply = (response.message.content or "").strip()
                self._history.append({"role": "assistant", "content": reply})
                result = reply

            if len(self._history) > MAX_HISTORY * 2:
                self._history = self._history[-(MAX_HISTORY * 2):]

            return result

        except Exception as e:
            logger.error("Brain error: %s", e)
            return None

    def reset_history(self):
        self._history.clear()
