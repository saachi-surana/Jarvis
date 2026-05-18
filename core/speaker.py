# Setup notes:
# Run the download script once to get Piper + the voice model:
#
#   bash ~/Projects/Jarvis/download_voice.sh
#
# That script will:
#   1. Download the Piper binary for your Mac architecture (arm64 or x86_64)
#      and place it at ~/Projects/Jarvis/piper/piper
#   2. Download the en_US-ryan-high voice model (.onnx + .onnx.json)
#      and place it at ~/Projects/Jarvis/voices/
#
# If you prefer to do it manually:
#   Piper releases: https://github.com/rhasspy/piper/releases
#   Voice model:    https://huggingface.co/rhasspy/piper-voices (en/en_US/ryan/high)
#
# Fallback: if the Piper binary or model is not found, macOS `say -v Samantha` is
# used automatically and a one-time warning is printed.

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import PIPER_BINARY, PIPER_MODEL

_piper_warned = False


def _resolve(path: str) -> str:
    return os.path.expanduser(path)


def _clean_text(text: str) -> str:
    """Strip markdown, JSON noise, and extra whitespace before speaking."""
    text = re.sub(r"```[\s\S]*?```", "", text)          # fenced code blocks
    text = re.sub(r"`[^`]*`", "", text)                  # inline code
    text = re.sub(r"\*+", "", text)                      # bold / italic
    text = re.sub(r"_+([^_]*)_+", r"\1", text)          # underscore emphasis
    text = re.sub(r"\{[^{}]*\}", "", text)               # JSON fragments
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  # markdown links
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headings
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _speak_piper(text: str) -> bool:
    """
    Speak via Piper TTS, piping raw PCM directly to afplay.
    Returns True on success, False if Piper is unavailable or errors.
    """
    global _piper_warned
    piper_bin   = _resolve(PIPER_BINARY)
    piper_model = _resolve(PIPER_MODEL)

    if not os.path.isfile(piper_bin):
        if not _piper_warned:
            print(f"[Speaker] Piper binary not found at {piper_bin}")
            print("[Speaker] Run:  bash ~/Projects/Jarvis/download_voice.sh")
            print("[Speaker] Falling back to macOS 'say'.")
            _piper_warned = True
        return False

    if not os.path.isfile(piper_model):
        if not _piper_warned:
            print(f"[Speaker] Voice model not found at {piper_model}")
            print("[Speaker] Run:  bash ~/Projects/Jarvis/download_voice.sh")
            print("[Speaker] Falling back to macOS 'say'.")
            _piper_warned = True
        return False

    try:
        # Piper outputs raw PCM: 16-bit signed LE, mono, 22050 Hz
        piper = subprocess.Popen(
            [piper_bin, "--model", piper_model, "--output_raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        raw_audio, piper_err = piper.communicate(input=text.encode("utf-8"))

        if piper.returncode != 0:
            print(f"[Speaker] Piper error: {piper_err.decode().strip()}")
            return False

        # afplay -f raw reads raw PCM from stdin
        afplay = subprocess.run(
            ["afplay", "-f", "raw", "-r", "22050", "-b", "16", "-c", "1", "-"],
            input=raw_audio,
            capture_output=True,
        )
        if afplay.returncode != 0:
            print(f"[Speaker] afplay error: {afplay.stderr.decode().strip()}")
            return False

        return True

    except Exception as exc:
        print(f"[Speaker] Piper playback failed: {exc}")
        return False


def _speak_say(text: str):
    """Fallback: macOS built-in TTS."""
    try:
        subprocess.run(["say", "-v", "Samantha", text], check=True)
    except Exception as exc:
        print(f"[Speaker] 'say' failed: {exc}")


def speak(text: str):
    """Clean text, echo to terminal, then speak via Piper (or 'say' fallback)."""
    cleaned = _clean_text(text)
    if not cleaned:
        return
    print(f"\nJarvis: {cleaned}\n")
    if not _speak_piper(cleaned):
        _speak_say(cleaned)
