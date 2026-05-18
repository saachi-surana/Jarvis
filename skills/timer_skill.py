import math
import struct
import sys
import os
import threading

import numpy as np
import pygame

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _generate_chime(frequency: int = 880, duration_ms: int = 400) -> bytes:
    sample_rate = 44100
    num_samples = int(sample_rate * duration_ms / 1000)
    buf = []
    for i in range(num_samples):
        t = i / sample_rate
        # Fade out over the last 20% of samples to avoid a hard click
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


def _fire(label: str):
    _play_chime()
    message = f"{label} is done."
    print(f"\n[Timer] {message}")
    try:
        from core.speaker import speak
        speak(message)
    except Exception as e:
        print(f"[Timer] Could not speak alert: {e}")


def execute(params: dict) -> str:
    try:
        duration_minutes = float(params.get("duration_minutes", 0))
    except (TypeError, ValueError):
        return "Please provide a valid duration in minutes."

    if duration_minutes <= 0:
        return "Duration must be greater than zero."

    label = str(params.get("label", "Timer")).strip() or "Timer"
    delay_seconds = duration_minutes * 60

    t = threading.Timer(delay_seconds, _fire, args=[label])
    t.daemon = True
    t.start()

    minutes_display = int(duration_minutes) if duration_minutes == int(duration_minutes) else duration_minutes
    return f"Got it — {label} set for {minutes_display} minute{'s' if duration_minutes != 1 else ''}."
