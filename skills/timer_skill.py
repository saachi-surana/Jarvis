import math
import struct
import sys
import os
import threading
import time

import numpy as np
import pygame

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _generate_chime(frequency: int = 880, duration_ms: int = 400) -> bytes:
    sample_rate = 44100
    num_samples = int(sample_rate * duration_ms / 1000)
    buf = []
    for i in range(num_samples):
        t = i / sample_rate
        fade = 1.0 - (i / num_samples) * 0.8
        sample = int(32767 * 0.4 * fade * math.sin(2 * math.pi * frequency * t))
        buf.append(struct.pack("<h", sample))
    return b"".join(buf)


def _play_chime():
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
        pcm = _generate_chime()
        sound = pygame.sndarray.make_sound(np.frombuffer(pcm, dtype=np.int16))
        sound.play()
        pygame.time.wait(500)
    except Exception as e:
        print(f"[Timer] Chime playback failed: {e}")


def _emit_to_hud(event: str, data: dict):
    """Lazily import socketio from the UI server and broadcast — no-op if unavailable."""
    try:
        from ui.server import socketio
        socketio.emit(event, data)
    except Exception:
        pass


def _parse_duration(params: dict) -> float:
    """
    Accept either duration_minutes (float) or duration (string like "5" or "5 minutes").
    Returns duration in minutes, or 0 on failure.
    """
    if "duration_minutes" in params:
        try:
            return float(params["duration_minutes"])
        except (TypeError, ValueError):
            pass
    if "duration" in params:
        raw = str(params["duration"]).strip().lower()
        # Strip non-numeric suffix ("5 minutes" → "5", "1.5min" → "1.5")
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


def execute(params: dict) -> str:
    duration_minutes = _parse_duration(params)

    if duration_minutes <= 0:
        return "Please provide a valid duration greater than zero."

    label = str(params.get("label", "Timer")).strip() or "Timer"
    delay_seconds = duration_minutes * 60

    stop_event = threading.Event()

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
        print(f"\n[Timer] {message}")
        _emit_to_hud("timer_done", {"label": label})
        try:
            from core.speaker import speak
            speak(message)
        except Exception as e:
            print(f"[Timer] Could not speak alert: {e}")

    threading.Thread(target=do_countdown, daemon=True).start()
    t = threading.Timer(delay_seconds, do_fire)
    t.daemon = True
    t.start()

    minutes_display = (
        int(duration_minutes) if duration_minutes == int(duration_minutes)
        else duration_minutes
    )
    return f"Got it — {label} set for {minutes_display} minute{'s' if duration_minutes != 1 else ''}."
