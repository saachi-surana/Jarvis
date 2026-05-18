# Setup notes:
# Requires Ollama running locally: https://ollama.com
# Pull the model first: ollama pull llama3.2
# Install the Python client: pip install ollama

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import OLLAMA_MODEL, OLLAMA_URL
from typing import Optional
import ollama

SYSTEM_PROMPT = (
    "You are Jarvis, a highly intelligent AI assistant for Saachi — inspired by the Jarvis from Iron Man. "
    "You are concise, witty, and speak with calm confidence. "
    "You have access to skills: calendar, tasks, studysync, system, web, timer. "
    'When the user\'s request requires a skill, respond ONLY with a valid JSON object in this format: {"action": "skill_name", "params": {}}. '
    "For general conversation, respond in plain text. "
    "Keep responses under 3 sentences unless the user asks for more detail."
)

MAX_HISTORY = 10


class Brain:
    def __init__(self):
        self._history: list[dict] = []
        self._client = ollama.Client(host=OLLAMA_URL)

    def think(self, user_input: str) -> Optional[str]:
        """
        Send user_input to Ollama and return the raw response string.
        Maintains a rolling window of the last MAX_HISTORY message pairs.
        """
        self._history.append({"role": "user", "content": user_input})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._history

        try:
            response = self._client.chat(
                model=OLLAMA_MODEL,
                messages=messages,
            )
            reply = response["message"]["content"].strip()
            self._history.append({"role": "assistant", "content": reply})
            # Keep only last MAX_HISTORY messages (user+assistant pairs)
            if len(self._history) > MAX_HISTORY * 2:
                self._history = self._history[-(MAX_HISTORY * 2):]
            return reply
        except Exception as e:
            print(f"[Brain] ERROR: {e}")
            return None

    def reset_history(self):
        self._history.clear()
