import base64
import json
import os
import subprocess
import time

import requests

CONFIG_PATH = os.path.expanduser("~/.notion-planner/config.json")
TOKEN_PATH  = os.path.expanduser("~/.notion-planner/spotify-token.json")
API_BASE    = "https://api.spotify.com/v1"


# ── credentials & token ─────────────────────────────────────────────────────

def _load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
    cfg = json.load(open(CONFIG_PATH))
    if not cfg.get("spotifyClientId") or not cfg.get("spotifyClientSecret"):
        raise KeyError("spotifyClientId / spotifyClientSecret missing from config.json")
    return cfg


def _load_token() -> dict:
    if not os.path.isfile(TOKEN_PATH):
        raise FileNotFoundError(
            f"Spotify token not found at {TOKEN_PATH}. "
            "Please run the Spotify OAuth flow first."
        )
    return json.load(open(TOKEN_PATH))


def _save_token(token: dict) -> None:
    os.makedirs(os.path.dirname(TOKEN_PATH), exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        json.dump(token, f, indent=2)


def _refresh_access_token(cfg: dict, token: dict) -> dict:
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise ValueError("No refresh_token in Spotify token file.")

    creds = base64.b64encode(
        f"{cfg['spotifyClientId']}:{cfg['spotifyClientSecret']}".encode()
    ).decode()

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=10,
    )
    resp.raise_for_status()
    new_token = resp.json()
    # Preserve refresh_token if Spotify doesn't rotate it
    if "refresh_token" not in new_token:
        new_token["refresh_token"] = refresh_token
    # expires_at stored in milliseconds to match the token file convention
    new_token["expires_at"] = int(time.time() * 1000) + new_token.get("expires_in", 3600) * 1000
    _save_token(new_token)
    return new_token


def _get_headers() -> dict:
    cfg   = _load_config()
    token = _load_token()
    # expires_at is a millisecond timestamp; give 60-second buffer
    if time.time() * 1000 >= token.get("expires_at", 0) - 60_000:
        token = _refresh_access_token(cfg, token)
    return {"Authorization": f"Bearer {token['access_token']}"}


# ── device recovery ──────────────────────────────────────────────────────────

def _open_spotify_and_get_device() -> str | None:
    """Launch Spotify, wait for it to register, return the first available device id."""
    subprocess.Popen(["open", "-a", "Spotify"])
    time.sleep(3)
    try:
        resp = requests.get(f"{API_BASE}/me/player/devices", headers=_get_headers(), timeout=10)
        if not resp.ok:
            return None
        devices = resp.json().get("devices", [])
        if not devices:
            return None
        # Prefer whichever device is already active, else take the first
        for d in devices:
            if d.get("is_active"):
                return d["id"]
        return devices[0]["id"]
    except Exception:
        return None


# ── low-level request helpers ────────────────────────────────────────────────

def _player_put(path: str, body: dict | None = None, device_id: str | None = None) -> str | None:
    """PUT to the player API. Returns an error string on failure, None on success."""
    headers = _get_headers()
    headers["Content-Type"] = "application/json"
    params  = {"device_id": device_id} if device_id else {}
    resp = requests.put(f"{API_BASE}{path}", headers=headers, json=body or {}, params=params, timeout=10)

    if resp.status_code in (404, 403) and not device_id:
        # No active device — open Spotify and retry once with an explicit device
        recovered_id = _open_spotify_and_get_device()
        if not recovered_id:
            return "Spotify isn't open on any device. I launched it — please try again in a moment."
        return _player_put(path, body, device_id=recovered_id)

    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:160]}"
    return None  # success


def _player_post(path: str, device_id: str | None = None) -> str | None:
    """POST to the player API. Returns an error string on failure, None on success."""
    headers = _get_headers()
    params  = {"device_id": device_id} if device_id else {}
    resp = requests.post(f"{API_BASE}{path}", headers=headers, params=params, timeout=10)

    if resp.status_code in (404, 403) and not device_id:
        recovered_id = _open_spotify_and_get_device()
        if not recovered_id:
            return "Spotify isn't open on any device. I launched it — please try again in a moment."
        return _player_post(path, device_id=recovered_id)

    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:160]}"
    return None


def _search(query: str, search_type: str) -> dict | None:
    resp = requests.get(
        f"{API_BASE}/search",
        headers=_get_headers(),
        params={"q": query, "type": search_type, "limit": 1},
        timeout=10,
    )
    if not resp.ok:
        return None
    return resp.json()


# ── actions ──────────────────────────────────────────────────────────────────

def _play(params: dict) -> str:
    err = _player_put("/me/player/play")
    return err or "Resuming playback."


def _pause(params: dict) -> str:
    err = _player_put("/me/player/pause")
    return err or "Paused."


def _next_track(params: dict) -> str:
    err = _player_post("/me/player/next")
    return err or "Skipped to the next track."


def _previous_track(params: dict) -> str:
    err = _player_post("/me/player/previous")
    return err or "Going back to the previous track."


def _what_playing(params: dict) -> str:
    resp = requests.get(
        f"{API_BASE}/me/player/currently-playing",
        headers=_get_headers(),
        timeout=10,
    )
    if resp.status_code == 204:
        return "Nothing is currently playing on Spotify."
    if not resp.ok:
        return f"Spotify error {resp.status_code}: {resp.text[:160]}"
    data = resp.json()
    item = data.get("item")
    if not item:
        return "Nothing is currently playing."
    track  = item.get("name", "Unknown")
    artist = ", ".join(a["name"] for a in item.get("artists", [])) or "Unknown"
    status = "Playing" if data.get("is_playing") else "Paused"
    return f"{status}: {track} by {artist}."


def _play_song(params: dict) -> str:
    query = str(params.get("query", "")).strip()
    if not query:
        return "Please specify a song to search for."

    result = _search(query, "track")
    if not result:
        return f"Couldn't search Spotify for '{query}'."
    tracks = result.get("tracks", {}).get("items", [])
    if not tracks:
        return f"No tracks found for '{query}'."

    track  = tracks[0]
    name   = track["name"]
    artist = ", ".join(a["name"] for a in track.get("artists", []))
    uri    = f"spotify:track:{track['id']}"

    err = _player_put("/me/player/play", {"uris": [uri]})
    return err or f"Playing {name} by {artist}."


def _play_artist(params: dict) -> str:
    query = str(params.get("query", "")).strip()
    if not query:
        return "Please specify an artist to play."

    result = _search(query, "artist")
    if not result:
        return f"Couldn't search Spotify for '{query}'."
    artists = result.get("artists", {}).get("items", [])
    if not artists:
        return f"No artist found for '{query}'."

    artist     = artists[0]
    artist_id  = artist["id"]
    name       = artist["name"]
    context_uri = f"spotify:artist:{artist_id}"

    err = _player_put("/me/player/play", {"context_uri": context_uri})
    return err or f"Playing music by {name}."


def _set_volume(params: dict) -> str:
    try:
        level = int(params.get("level", 50))
    except (ValueError, TypeError):
        return "Please provide a volume level between 0 and 100."
    level = max(0, min(100, level))

    resp = requests.put(
        f"{API_BASE}/me/player/volume",
        headers=_get_headers(),
        params={"volume_percent": level},
        timeout=10,
    )
    if resp.status_code in (404, 403):
        recovered_id = _open_spotify_and_get_device()
        if not recovered_id:
            return "Spotify isn't open on any device. I launched it — please try again in a moment."
        resp = requests.put(
            f"{API_BASE}/me/player/volume",
            headers=_get_headers(),
            params={"volume_percent": level, "device_id": recovered_id},
            timeout=10,
        )
    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:160]}"
    return f"Volume set to {level}%."


# ── dispatch ─────────────────────────────────────────────────────────────────

_ACTIONS = {
    "play":         _play,
    "pause":        _pause,
    "next":         _next_track,
    "previous":     _previous_track,
    "what_playing": _what_playing,
    "play_song":    _play_song,
    "play_artist":  _play_artist,
    "volume":       _set_volume,
}


def execute(params: dict) -> str:
    action = str(params.get("action", "")).strip()
    if not action:
        return "No Spotify action specified."
    handler = _ACTIONS.get(action)
    if not handler:
        return f"Unknown Spotify action: '{action}'."
    try:
        return handler(params)
    except FileNotFoundError as e:
        return str(e)
    except KeyError as e:
        return f"Missing Spotify config: {e}"
    except requests.exceptions.ConnectionError:
        return "Couldn't reach Spotify — check your internet connection."
    except requests.exceptions.Timeout:
        return "Spotify request timed out."
    except Exception as e:
        return f"Spotify error: {e}"
