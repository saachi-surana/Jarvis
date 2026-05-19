# Setup notes:
# 1. Install dependencies: pip install -r requirements.txt
# 2. Start Ollama and pull the model: ollama serve && ollama pull llama3.2
# 3. (Optional) Place Piper binary + voice model per instructions in core/speaker.py
#    Run once: bash ~/Projects/Jarvis/download_voice.sh
# 4. Run: python main.py

import sys
import os
import subprocess
import threading
import time
import requests

sys.path.insert(0, os.path.dirname(__file__))

from config import OLLAMA_URL
from core.transcriber import Transcriber
from core.brain import Brain
from core.router import Router
from core.speaker import speak
from core.listener import Listener
import ui.server as ui_server

# Shared pipeline singletons
_transcriber: Transcriber = None
_brain: Brain = None
_router: Router = None


def _check_ollama() -> bool:
    try:
        resp = requests.get(OLLAMA_URL, timeout=3)
        return resp.status_code == 200
    except requests.exceptions.ConnectionError:
        return False


_DISMISS_PHRASES = ("thank you", "thanks", "that's all", "thats all")
_DISMISS_REPLY   = "Of course, Saachi. I'll be here when you need me."


def process_input(text: str, on_response=None):
    if not text or not text.strip():
        return

    # Farewell — skip the brain and return to wake-word standby
    lower = text.strip().lower()
    if any(phrase in lower for phrase in _DISMISS_PHRASES):
        print(f"[You]: {text}")
        speak(_DISMISS_REPLY)
        if on_response:
            on_response(_DISMISS_REPLY)
        return

    print(f"[You]: {text}")
    raw = _brain.think(text)
    if raw is None:
        msg = "I seem to be having trouble thinking right now. Is Ollama still running?"
        speak(msg)
        if on_response:
            on_response(msg)
        return
    response = _router.route(raw)
    speak(response)
    if on_response:
        on_response(response)


def main():
    global _transcriber, _brain, _router

    # ── Startup check ──────────────────────────────────────────────────────
    if not _check_ollama():
        print("\n[ERROR] Ollama is not running. Start it with:  ollama serve\n")
        sys.exit(1)

    # ── Init pipeline ──────────────────────────────────────────────────────
    _transcriber = Transcriber()
    _brain = Brain()
    _router = Router()
    # Placeholder callback — replaced by ui.on_audio_received below
    listener = Listener(on_audio_callback=lambda _: None)

    # ── Status report ──────────────────────────────────────────────────────
    from config import PIPER_MODEL
    piper_model = os.path.expanduser(PIPER_MODEL)
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if elevenlabs_key:
        voice_status = "ElevenLabs (Josh)"
    elif os.path.isfile(piper_model):
        voice_status = "Piper TTS (Alan, en_GB)"
    else:
        voice_status = "macOS 'say' (Daniel) fallback"
    print("\n=== Jarvis System Status ===")
    print(f"  Ollama          ✓  ({OLLAMA_URL})")
    print(f"  Wake word       {listener.wake_word_status}")
    print(f"  Voice engine    {voice_status}")
    print("============================\n")

    # ── Init web UI server ─────────────────────────────────────────────────
    ui_server.init(process_input, listener, _transcriber)

    flask_thread = threading.Thread(
        target=ui_server.run,
        kwargs={"host": "127.0.0.1", "port": 5001},
        daemon=True,
    )
    flask_thread.start()

    # ── Start listener in background ───────────────────────────────────────
    listener.start()

    # ── Open Chrome app window ─────────────────────────────────────────────
    time.sleep(1)
    subprocess.Popen([
        "open", "-a", "Brave Browser",
        "--args",
        "--app=http://localhost:5001",
        "--window-size=480,700",
    ])

    # ── Startup announcement ───────────────────────────────────────────────
    _STARTUP_MSG = "Jarvis online. Good to see you again."
    threading.Thread(target=lambda: speak(_STARTUP_MSG), daemon=True).start()

    # ── Keep main thread alive ─────────────────────────────────────────────
    stop_event = threading.Event()
    try:
        while not stop_event.wait(timeout=1):
            pass
    except KeyboardInterrupt:
        print("\n[Jarvis] Shutting down.")
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
