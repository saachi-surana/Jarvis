import os
import re
import subprocess
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import PIPER_MODEL

_ELEVENLABS_VOICE_ID = "TxGEqnHWrfWFTfGW9XjX"
_ELEVENLABS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{_ELEVENLABS_VOICE_ID}"
_TMP_MP3 = "/tmp/jarvis_tts.mp3"
_TMP_WAV = "/tmp/jarvis_tts.wav"

_piper_warned = False


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
            print(f"[Speaker] ElevenLabs error {resp.status_code}: {resp.text[:200]}")
            return False

        with open(_TMP_MP3, "wb") as f:
            f.write(resp.content)

        result = subprocess.run(["afplay", _TMP_MP3], capture_output=True)
        if result.returncode != 0:
            print(f"[Speaker] afplay error: {result.stderr.decode().strip()}")
            return False

        return True

    except Exception as exc:
        print(f"[Speaker] ElevenLabs playback failed: {exc}")
        return False


def _speak_piper(text: str) -> bool:
    global _piper_warned
    piper_model = os.path.expanduser(PIPER_MODEL)

    if not os.path.isfile(piper_model):
        if not _piper_warned:
            print(f"[Speaker] Piper model not found at {piper_model}")
            print("[Speaker] Download en_GB-alan-low from https://huggingface.co/rhasspy/piper-voices")
            print("[Speaker] Falling back to macOS 'say'.")
            _piper_warned = True
        return False

    try:
        # python3 -m piper reads text from stdin, writes WAV to --output_file
        result = subprocess.run(
            ["python3", "-m", "piper", "--model", piper_model, "--output_file", _TMP_WAV],
            input=text.encode("utf-8"),
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"[Speaker] Piper error: {result.stderr.decode().strip()}")
            return False

        afplay = subprocess.run(["afplay", _TMP_WAV], capture_output=True)
        if afplay.returncode != 0:
            print(f"[Speaker] afplay error: {afplay.stderr.decode().strip()}")
            return False

        return True

    except Exception as exc:
        print(f"[Speaker] Piper playback failed: {exc}")
        return False


def _speak_say(text: str):
    try:
        subprocess.run(["say", "-v", "Daniel", text], check=True)
    except Exception as exc:
        print(f"[Speaker] 'say' failed: {exc}")


def _tts_text(text: str) -> str:
    """Apply TTS-only substitutions that fix pronunciation without altering displayed text."""
    return text.replace("Saachi", "Saachee")


def speak(text: str):
    cleaned = _clean_text(text)
    if not cleaned:
        return
    print(f"\nJarvis: {cleaned}\n")
    tts = _tts_text(cleaned)
    if _speak_elevenlabs(tts):
        return
    if _speak_piper(tts):
        return
    _speak_say(tts)
