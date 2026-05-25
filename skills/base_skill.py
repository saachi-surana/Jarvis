import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.logger import logger


class BaseSkill:
    name        = "base"
    description = "Base skill class"

    def execute(self, params: dict) -> str:
        raise NotImplementedError

    def error(self, msg: str) -> str:
        logger.error("[%s] %s", self.name, msg)
        return f"Sorry, {msg}"

    def log(self, msg: str) -> None:
        logger.info("[%s] %s", self.name, msg)
