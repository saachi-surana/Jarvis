import os
import re
import sys
import threading
import time

import requests
from ddgs import DDGS
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = "jarvis-hud-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_process_input_fn  = None
_listener          = None
_transcriber       = None
_studysync_courses = []  # cached list of course name strings
_weather           = {"temp": "69", "desc": "SEATTLE, WA", "feels": "69"}
_now_playing       = {"artist": "--", "track": "--"}


# ── Weather poller ────────────────────────────────────────────────────────────

def _fetch_weather() -> dict:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(
                "Seattle weather right now temperature",
                max_results=3,
            ))
        temp, desc = None, None
        for r in results:
            text = r.get("body", "") + " " + r.get("title", "")
            if temp is None:
                m = re.search(r"(\d{2,3})\s*°?\s*F", text)
                if m:
                    temp = m.group(1)
            if desc is None:
                for word in ("sunny", "cloudy", "rain", "snow", "fog",
                             "overcast", "clear", "drizzle", "storm", "partly"):
                    if word in text.lower():
                        desc = word.upper()
                        break
            if temp and desc:
                break
        return {
            "temp":  temp or "68",
            "feels": temp or "68",
            "desc":  desc or "PARTLY CLOUDY",
        }
    except Exception as e:
        print(f"[Server] Weather fetch failed: {e}")
        return {}


def _weather_poller():
    global _weather
    while True:
        result = _fetch_weather()
        if result:
            _weather = result
            socketio.emit("weather_update", _weather)
            print(f"[Server] Weather: {_weather['temp']}°F ({_weather['desc']})")
        time.sleep(600)  # 10 minutes


# ── Spotify poller ───────────────────────────────────────────────────────────

def _fetch_now_playing() -> dict:
    try:
        from skills.spotify_skill import execute as spotify_execute
        result = spotify_execute({"action": "what_playing"})
        print(f"[Server] Spotify raw: {result!r}")
        if result.startswith("Playing:"):
            m = re.match(r"Playing: (.+) by (.+)\.", result)
            if m:
                return {"track": m.group(1), "artist": m.group(2)}
    except Exception as e:
        print(f"[Server] Spotify fetch failed: {e}")
    return {"artist": "--", "track": "--"}


def _spotify_poller():
    global _now_playing
    while True:
        time.sleep(30)
        data = _fetch_now_playing()
        if data["track"] != _now_playing["track"] or data["artist"] != _now_playing["artist"]:
            _now_playing = data
            socketio.emit("now_playing_update", _now_playing)
            print(f"[Server] Now playing: {data['track']} — {data['artist']}")


# ── StudySync poller ─────────────────────────────────────────────────────────

def _fetch_studysync_courses() -> list:
    """Fetch course list from StudySync. Returns [] if offline."""
    try:
        from config import STUDYSYNC_URL
        resp = requests.get(f"{STUDYSYNC_URL}/courses", timeout=5)
        if not resp.ok:
            return []
        data = resp.json()
        # /courses may return a list of dicts with a "name" key, or plain strings
        courses = []
        for item in data:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or item.get("course_name", "")
                if name:
                    courses.append(str(name))
            elif isinstance(item, str) and item:
                courses.append(item)
        return courses
    except Exception as e:
        print(f"[Server] StudySync fetch failed: {e}")
        return []


def _studysync_poller():
    global _studysync_courses
    while True:
        courses = _fetch_studysync_courses()
        _studysync_courses = courses
        socketio.emit("studysync_update", {"courses": courses})
        print(f"[Server] StudySync poller emitted {len(courses)} courses.")
        time.sleep(1800)  # 30 minutes


# ── Init & run ────────────────────────────────────────────────────────────────

def init(process_input_fn, listener, transcriber):
    global _process_input_fn, _listener, _transcriber
    _process_input_fn = process_input_fn
    _listener         = listener
    _transcriber      = transcriber
    listener.on_audio = on_audio_received

    # Fetch Spotify state synchronously so _now_playing is ready before any client connects
    global _now_playing
    _now_playing = _fetch_now_playing()
    print(f"[Server] Initial now_playing: {_now_playing}")

    # Start background pollers
    threading.Thread(target=_weather_poller, daemon=True).start()
    threading.Thread(target=_studysync_poller, daemon=True).start()
    threading.Thread(target=_spotify_poller, daemon=True).start()


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

@socketio.on("connect")
def handle_connect():
    """Push cached state to a newly connected client."""
    emit("studysync_update", {"courses": _studysync_courses})
    emit("weather_update", _weather)
    emit("now_playing_update", _now_playing)


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
