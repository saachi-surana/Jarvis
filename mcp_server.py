import asyncio
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("jarvis")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="jarvis_calendar",
            description="Read or create events on Saachi's Google Calendar",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["today", "tomorrow", "week", "next_event", "create"],
                        "description": (
                            "Use 'today', 'tomorrow', 'week', or 'next_event' to read events. "
                            "Use 'create' to add a new event (requires title, date, start_time, end_time)."
                        ),
                    },
                    "title":      {"type": "string", "description": "Event title (create only)"},
                    "date":       {"type": "string", "description": "Date in YYYY-MM-DD format (create only)"},
                    "start_time": {"type": "string", "description": "Start time HH:MM 24-hour (create only)"},
                    "end_time":   {"type": "string", "description": "End time HH:MM 24-hour (create only)"},
                },
                "required": ["action"],
            },
        ),
        types.Tool(
            name="jarvis_tasks",
            description="Read and manage Saachi's task list",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "list_today", "add", "done"],
                        "description": "'list' all tasks, 'list_today' for today's tasks, 'add' a task, 'done' to mark complete",
                    },
                    "text": {"type": "string", "description": "Task description (add or done)"},
                    "date": {
                        "type": "string",
                        "description": "Use 'TODAY' for today, or YYYY-MM-DD (add only)",
                    },
                },
                "required": ["action"],
            },
        ),
        types.Tool(
            name="jarvis_spotify",
            description="Control Saachi's Spotify playback",
            inputSchema={
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
                        "description": "Volume 0–100 for volume action",
                    },
                },
                "required": ["action"],
            },
        ),
        types.Tool(
            name="jarvis_studysync",
            description="Access Saachi's StudySync courses and lectures",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_courses", "list_lectures", "search"],
                    },
                    "course": {"type": "string", "description": "Course name filter"},
                    "query":  {"type": "string", "description": "Search query (search action)"},
                },
                "required": ["action"],
            },
        ),
        types.Tool(
            name="jarvis_search",
            description="Search across Saachi's tasks, calendar, and StudySync",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["all", "tasks", "calendar", "studysync"],
                        "description": "Limit search to a specific source (default: all)",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="jarvis_system",
            description="Get system info: current time or Seattle weather",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get_time", "get_weather"],
                    },
                },
                "required": ["action"],
            },
        ),
    ]


# Maps MCP tool names → (skill module, function name)
_SKILL_MAP = {
    "jarvis_calendar":  ("skills.calendar_skill",  "execute"),
    "jarvis_tasks":     ("skills.tasks_skill",      "execute"),
    "jarvis_spotify":   ("skills.spotify_skill",    "execute"),
    "jarvis_studysync": ("skills.studysync_skill",  "execute"),
    "jarvis_search":    ("skills.search_skill",     "execute"),
    "jarvis_system":    ("skills.system_skill",     "execute"),
}


def _normalize_params(tool_name: str, arguments: dict) -> dict:
    """
    Translate MCP tool arguments to the parameter format each skill expects.

    The calendar skill dispatches on params.get("action") == "create" for writes
    and params.get("query") for reads.  The MCP schema exposes a single "action"
    enum covering both cases, so we remap read values into "query" here.
    """
    params = dict(arguments)

    if tool_name == "jarvis_calendar":
        action = params.get("action", "")
        if action in ("today", "tomorrow", "week", "next_event"):
            # Skill reads via params["query"]; remove the "action" key
            params["query"] = action
            params.pop("action", None)
        # "create" stays as-is — skill checks params.get("action") == "create"

    return params


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name not in _SKILL_MAP:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    module_path, func_name = _SKILL_MAP[name]

    try:
        module  = importlib.import_module(module_path)
        execute = getattr(module, func_name)
        params  = _normalize_params(name, arguments)
        result  = execute(params)
        return [types.TextContent(type="text", text=str(result))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error calling {name}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
