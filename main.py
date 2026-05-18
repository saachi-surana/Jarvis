# Setup notes:
# 1. Install dependencies: pip install -r requirements.txt
# 2. Start Ollama and pull the model: ollama serve && ollama pull llama3.2
# 3. (Optional) Set PORCUPINE_ACCESS_KEY for wake word: export PORCUPINE_ACCESS_KEY="..."
# 4. (Optional) Place Piper binary + voice model per instructions in core/speaker.py
# 5. macOS Accessibility permission required for Cmd+Shift+J hotkey (pynput)
# 6. Run: python main.py

import sys
import os
import threading
import tkinter as tk
import requests

sys.path.insert(0, os.path.dirname(__file__))

from config import OLLAMA_URL
from core.transcriber import Transcriber
from core.brain import Brain
from core.router import Router
from core.speaker import speak
from core.listener import Listener
from ui.app import JarvisApp

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


def process_input(text: str, on_response=None):
    """
    Shared pipeline entry point: text → brain → router → speaker.
    Called by the UI (text entry, mic button) and the wake-word listener thread.

    on_response: optional callable(response_str) invoked after speak() completes,
                 used by the UI to display the response without blocking the main thread.
    """
    if not text or not text.strip():
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
    piper_bin   = os.path.expanduser("~/jarvis/piper/piper")
    piper_model = os.path.expanduser("~/jarvis/voices/jarvis.onnx")
    voice_status = (
        "Piper TTS"
        if os.path.isfile(piper_bin) and os.path.isfile(piper_model)
        else "macOS 'say' (Samantha) fallback"
    )
    print("\n=== Jarvis System Status ===")
    print(f"  Ollama          ✓  ({OLLAMA_URL})")
    print(f"  Wake word       {listener.wake_word_status}")
    print(f"  Voice engine    {voice_status}")
    print("============================\n")

    # ── Build UI (must run in main thread) ─────────────────────────────────
    root = tk.Tk()
    ui = JarvisApp(
        root,
        process_input_fn=process_input,
        listener=listener,
        transcriber=_transcriber,
    )

    # Wire listener → UI so audio from wake word also appears in the conversation
    listener.on_audio = ui.on_audio_received

    # ── Start listener in background ───────────────────────────────────────
    listener.start()

    # ── Startup announcement ───────────────────────────────────────────────
    _STARTUP_MSG = "Jarvis online. Good to see you again."

    def _speak_startup():
        speak(_STARTUP_MSG)

    threading.Thread(target=_speak_startup, daemon=True).start()
    root.after(400, lambda: ui.add_message("jarvis", _STARTUP_MSG))

    # ── Run UI (blocks until window is closed) ─────────────────────────────
    try:
        ui.run()
    except KeyboardInterrupt:
        print("\n[Jarvis] Shutting down.")
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
