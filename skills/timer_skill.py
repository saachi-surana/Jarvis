import subprocess
import sys
import os
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from base_skill import BaseSkill
from core.logger import logger
from config import TIMER_CHIME_SOUND


def _play_chime() -> None:
    try:
        subprocess.run(["afplay", TIMER_CHIME_SOUND], capture_output=True)
    except Exception as e:
        logger.error("Timer chime playback failed: %s", e)


def _emit_to_hud(event: str, data: dict) -> None:
    try:
        from ui.server import socketio
        socketio.emit(event, data)
    except Exception:
        pass


def _parse_duration(params: dict) -> float:
    if "duration_minutes" in params:
        try:
            return float(params["duration_minutes"])
        except (TypeError, ValueError):
            pass
    if "duration" in params:
        raw     = str(params["duration"]).strip().lower()
        numeric = ""
        for ch in raw:
            if ch.isdigit() or ch == ".":
                numeric += ch
            elif numeric:
                break
        try:
            return float(numeric)
        except (TypeError, ValueError):
            pass
    return 0.0


def _execute(params: dict) -> str:
    duration_minutes = _parse_duration(params)

    if duration_minutes <= 0:
        return "Please provide a valid duration greater than zero."

    label         = str(params.get("label", "Timer")).strip() or "Timer"
    delay_seconds = duration_minutes * 60
    stop_event    = threading.Event()

    def do_countdown():
        remaining = int(delay_seconds)
        while remaining > 0 and not stop_event.is_set():
            _emit_to_hud("timer_update", {"label": label, "remaining": remaining})
            time.sleep(1)
            remaining -= 1

    def do_fire():
        stop_event.set()
        _play_chime()
        message = f"{label} is done."
        logger.info("Timer fired: %s", message)
        _emit_to_hud("timer_done", {"label": label})
        try:
            from core.speaker import speak
            speak(message)
        except Exception as e:
            logger.error("Timer could not speak alert: %s", e)

    threading.Thread(target=do_countdown, daemon=True).start()
    t = threading.Timer(delay_seconds, do_fire)
    t.daemon = True
    t.start()

    minutes_display = (
        int(duration_minutes) if duration_minutes == int(duration_minutes)
        else duration_minutes
    )
    return f"Got it — {label} set for {minutes_display} minute{'s' if duration_minutes != 1 else ''}."


class TimerSkill(BaseSkill):
    name        = "timer"
    description = "Countdown timers with chime and voice alert"

    def execute(self, params: dict) -> str:
        return _execute(params)


execute = TimerSkill().execute
