import os
import re
import subprocess
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import PIPER_MODEL
from core.logger import logger

_ELEVENLABS_VOICE_ID = "TxGEqnHWrfWFTfGW9XjX"
_ELEVENLABS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{_ELEVENLABS_VOICE_ID}"
_TMP_MP3 = "/tmp/jarvis_tts.mp3"
_TMP_WAV = "/tmp/jarvis_tts.wav"

_piper_warned = False
is_speaking   = False  # read by listener.py to suppress recording during playback


def _clean_text(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"_+([^_]*)_+", r"\1", text)
    text = re.sub(r"\{[^{}]*\}", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _speak_elevenlabs(text: str) -> bool:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return False

    try:
        resp = requests.post(
            _ELEVENLABS_URL,
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.75, "similarity_boost": 0.75},
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error("ElevenLabs error %d: %s", resp.status_code, resp.text[:200])
            return False

        with open(_TMP_MP3, "wb") as f:
            f.write(resp.content)

        result = subprocess.run(["afplay", _TMP_MP3], capture_output=True)
        if result.returncode != 0:
            logger.error("afplay error: %s", result.stderr.decode().strip())
            return False

        return True

    except Exception as exc:
        logger.error("ElevenLabs playback failed: %s", exc)
        return False


def _speak_piper(text: str) -> bool:
    global _piper_warned
    piper_model = os.path.expanduser(PIPER_MODEL)

    if not os.path.isfile(piper_model):
        if not _piper_warned:
            logger.warning("Piper model not found at %s — falling back to macOS 'say'.", piper_model)
            _piper_warned = True
        return False

    try:
        result = subprocess.run(
            ["python3", "-m", "piper", "--model", piper_model, "--output_file", _TMP_WAV],
            input=text.encode("utf-8"),
            capture_output=True,
        )
        if result.returncode != 0:
            logger.error("Piper error: %s", result.stderr.decode().strip())
            return False

        afplay = subprocess.run(["afplay", _TMP_WAV], capture_output=True)
        if afplay.returncode != 0:
            logger.error("afplay error: %s", afplay.stderr.decode().strip())
            return False

        return True

    except Exception as exc:
        logger.error("Piper playback failed: %s", exc)
        return False


def _speak_say(text: str):
    try:
        subprocess.run(["say", "-v", "Daniel", text], check=True)
    except Exception as exc:
        logger.error("'say' failed: %s", exc)


def _tts_text(text: str) -> str:
    """Apply TTS-only substitutions that fix pronunciation without altering displayed text."""
    return text.replace("Saachi", "Saachee")


def speak(text: str):
    global is_speaking
    cleaned = _clean_text(text)
    if not cleaned:
        return
    logger.info("Jarvis: %s", cleaned)
    tts = _tts_text(cleaned)
    is_speaking = True
    try:
        if _speak_elevenlabs(tts):
            return
        if _speak_piper(tts):
            return
        _speak_say(tts)
    finally:
        is_speaking = False
