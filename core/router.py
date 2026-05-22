import json
import importlib
import os
import sys
from typing import Union

SKILL_MAP = {
    "calendar":  "calendar_skill",
    "tasks":     "tasks_skill",
    "studysync": "studysync_skill",
    "system":    "system_skill",
    "web":       "web_skill",
    "timer":     "timer_skill",
    "spotify":   "spotify_skill",
    "search":    "search_skill",
    "browser":   "browser_skill",
    "file":      "file_skill",
}

_MALFORMED = object()  # sentinel: JSON-like content found but couldn't parse


class Router:
    def __init__(self):
        skills_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "skills"))
        if skills_dir not in sys.path:
            sys.path.insert(0, skills_dir)

    def route(self, brain_output: str) -> str:
        if not brain_output:
            return "I didn't catch that. Could you repeat?"

        result = self._try_parse_json(brain_output)

        if result is _MALFORMED:
            return "I didn't quite understand that. Could you rephrase?"

        if isinstance(result, dict) and "action" in result:
            action = result["action"]
            params = result.get("params", {})
            # Intercept: if system skill gets a music-sounding action, redirect to spotify
            if action == "system" and params.get("action") in (
                "play_music", "play_song", "play_artist", "play", "pause_music",
                "pause", "next_track", "previous_track", "skip",
            ):
                print(f"[Router] Intercepting system music action → spotify: {params}")
                return self._dispatch_skill("spotify", params)
            return self._dispatch_skill(action, params)

        return brain_output

    def _try_parse_json(self, text: str) -> Union[dict, object, None]:
        text = text.strip()

        # Strip markdown fences
        if text.startswith("```"):
            lines = text.splitlines()
            inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            text = "\n".join(inner).strip()

        # Fast path: the whole string is JSON
        if text.startswith("{"):
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass

        # Find the first { ... } block anywhere
        brace_pos = text.find("{")
        if brace_pos == -1:
            return None

        depth = 0
        end_pos = -1
        for i, ch in enumerate(text[brace_pos:], brace_pos):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_pos = i
                    break

        if end_pos == -1:
            return _MALFORMED

        candidate = text[brace_pos:end_pos + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            return _MALFORMED

        return None

    def _dispatch_skill(self, action: str, params: dict) -> str:
        print(f"[Router] dispatch → action={action!r}  params={params}")
        module_name = SKILL_MAP.get(action)
        if not module_name:
            return f"I don't have a skill for '{action}' yet."
        try:
            module = importlib.import_module(module_name)
            # Force reload so code changes take effect without restart
            importlib.reload(module)
            execute_fn = getattr(module, "execute", None)
            if execute_fn is None:
                return f"Skill '{action}' is missing an execute() function."
            result = execute_fn(params)
            import asyncio
            if asyncio.iscoroutine(result):
                result = asyncio.get_event_loop().run_until_complete(result)
            return str(result)
        except ModuleNotFoundError as e:
            print(f"[Router] ModuleNotFoundError for {action}: {e}")
            return f"Skill '{action}' hasn't been built yet."
        except Exception as e:
            print(f"[Router] Exception in {action}: {e}")
            return f"Something went wrong with the {action} skill: {e}"
