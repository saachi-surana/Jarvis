# Setup notes:
# Skills live in jarvis/skills/ and must each expose:
#   execute(params: dict) -> str
# Skills are imported dynamically by action name.

import json
import importlib
import os
import sys
from typing import Optional

# Map action names to skill module names
SKILL_MAP = {
    "calendar": "calendar_skill",
    "tasks": "tasks_skill",
    "studysync": "studysync_skill",
    "system": "system_skill",
    "web": "web_skill",
    "timer": "timer_skill",
}


class Router:
    def __init__(self):
        # Ensure the skills directory is on sys.path
        skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
        skills_dir = os.path.abspath(skills_dir)
        if skills_dir not in sys.path:
            sys.path.insert(0, skills_dir)

    def route(self, brain_output: str) -> str:
        """
        Parse brain output. If it's a JSON skill dispatch, call the skill.
        Otherwise return the plain text directly.
        """
        if not brain_output:
            return "I didn't catch that. Could you repeat?"

        # Attempt JSON parse
        parsed = self._try_parse_json(brain_output)
        if parsed is not None and "action" in parsed:
            return self._dispatch_skill(parsed["action"], parsed.get("params", {}))

        # Plain text response
        return brain_output

    def _try_parse_json(self, text: str) -> Optional[dict]:
        text = text.strip()
        # Sometimes the model wraps JSON in markdown code fences
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    def _dispatch_skill(self, action: str, params: dict) -> str:
        module_name = SKILL_MAP.get(action)
        if not module_name:
            return f"I don't have a skill for '{action}' yet."
        try:
            module = importlib.import_module(module_name)
            execute_fn = getattr(module, "execute", None)
            if execute_fn is None:
                return f"Skill '{action}' is missing an execute() function."
            result = execute_fn(params)
            # Support coroutines (async execute)
            import asyncio
            if asyncio.iscoroutine(result):
                result = asyncio.get_event_loop().run_until_complete(result)
            return str(result)
        except ModuleNotFoundError:
            return f"Skill '{action}' hasn't been built yet."
        except Exception as e:
            return f"Something went wrong with the {action} skill: {e}"
