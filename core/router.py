import importlib
import os
import sys
from typing import Union

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.logger import logger

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


class Router:
    def __init__(self):
        skills_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "skills"))
        if skills_dir not in sys.path:
            sys.path.insert(0, skills_dir)

    def route(self, brain_output: Union[str, dict, None]) -> str:
        if not brain_output:
            return "I didn't catch that. Could you repeat?"

        if isinstance(brain_output, dict) and "action" in brain_output:
            action = brain_output["action"]
            params = brain_output.get("params", {})
            # Intercept: if system skill gets a music-sounding action, redirect to spotify
            if action == "system" and params.get("action") in (
                "play_music", "play_song", "play_artist", "play", "pause_music",
                "pause", "next_track", "previous_track", "skip",
            ):
                logger.info("Intercepting system music action → spotify: %s", params)
                return self._dispatch_skill("spotify", params)
            return self._dispatch_skill(action, params)

        if isinstance(brain_output, str):
            return brain_output

        return "I didn't quite understand that. Could you rephrase?"

    def _dispatch_skill(self, action: str, params: dict) -> str:
        logger.info("Dispatch → action=%r  params=%s", action, params)
        module_name = SKILL_MAP.get(action)
        if not module_name:
            return f"I don't have a skill for '{action}' yet."
        try:
            module = importlib.import_module(module_name)
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
            logger.error("ModuleNotFoundError for %s: %s", action, e)
            return f"Skill '{action}' hasn't been built yet."
        except Exception as e:
            logger.error("Exception in %s: %s", action, e)
            return f"Something went wrong with the {action} skill: {e}"
