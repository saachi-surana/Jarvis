import os
import sys
import threading

from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = "jarvis-hud-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_process_input_fn = None
_listener         = None
_transcriber      = None


def init(process_input_fn, listener, transcriber):
    global _process_input_fn, _listener, _transcriber
    _process_input_fn = process_input_fn
    _listener         = listener
    _transcriber      = transcriber
    listener.on_audio = on_audio_received


def run(host="127.0.0.1", port=5001):
    socketio.run(
        app,
        host=host,
        port=port,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
        log_output=False,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── SocketIO events ───────────────────────────────────────────────────────────

@socketio.on("user_input")
def handle_user_input(data):
    text = (data.get("text") or "").strip()
    if not text:
        return
    emit("status_update", {"state": "thinking", "text": "PROCESSING..."})

    def run_pipeline():
        def on_resp(r):
            socketio.emit("jarvis_response", {"text": r})
            socketio.emit("status_update", {"state": "ready", "text": "SYSTEM READY"})

        _process_input_fn(text, on_response=on_resp)

    threading.Thread(target=run_pipeline, daemon=True).start()


@socketio.on("mic_trigger")
def handle_mic_trigger():
    emit("status_update", {"state": "listening", "text": "LISTENING..."})

    def record():
        # trigger_recording records audio then calls on_audio_received synchronously.
        # on_audio_received immediately spawns its own thread so this returns fast.
        _listener.trigger_recording()

    threading.Thread(target=record, daemon=True).start()


# ── Audio callback (called by listener thread) ────────────────────────────────

def on_audio_received(audio_bytes: bytes):
    """
    Wired into listener.on_audio by init().
    Returns immediately — heavy work runs in its own thread.
    """
    def process():
        socketio.emit("status_update", {"state": "transcribing", "text": "TRANSCRIBING..."})
        text = _transcriber.transcribe(audio_bytes)
        if text:
            socketio.emit("user_message", {"text": text})
            socketio.emit("status_update", {"state": "thinking", "text": "PROCESSING..."})

            def on_resp(r):
                socketio.emit("jarvis_response", {"text": r})
                socketio.emit("status_update", {"state": "ready", "text": "SYSTEM READY"})

            _process_input_fn(text, on_response=on_resp)
        else:
            socketio.emit("status_update", {"state": "ready", "text": "SYSTEM READY"})

    threading.Thread(target=process, daemon=True).start()
