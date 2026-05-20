import base64
import json
import os
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
            "Spotify token not found. Please run the Spotify OAuth flow first "
            f"and save the token to {TOKEN_PATH}."
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
    # Preserve the refresh token if Spotify doesn't rotate it
    if "refresh_token" not in new_token:
        new_token["refresh_token"] = refresh_token
    new_token["expires_at"] = time.time() + new_token.get("expires_in", 3600)
    _save_token(new_token)
    return new_token


def _get_headers() -> dict:
    cfg   = _load_config()
    token = _load_token()
    # Refresh if expired or within 60 s of expiry
    if time.time() >= token.get("expires_at", 0) - 60:
        token = _refresh_access_token(cfg, token)
    return {"Authorization": f"Bearer {token['access_token']}"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _no_device_msg(resp: requests.Response) -> str | None:
    if resp.status_code == 404:
        return "No active Spotify device found. Open Spotify on any device and try again."
    if resp.status_code == 403:
        return "Spotify returned Forbidden — you may need Spotify Premium for playback control."
    return None


def _player_put(path: str, body: dict | None = None) -> str:
    headers = _get_headers()
    if body:
        headers["Content-Type"] = "application/json"
    resp = requests.put(f"{API_BASE}{path}", headers=headers, json=body, timeout=10)
    err = _no_device_msg(resp)
    if err:
        return err
    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:120]}"
    return None  # success


def _player_post(path: str) -> str:
    resp = requests.post(f"{API_BASE}{path}", headers=_get_headers(), timeout=10)
    err = _no_device_msg(resp)
    if err:
        return err
    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:120]}"
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
    resp = requests.get(f"{API_BASE}/me/player/currently-playing", headers=_get_headers(), timeout=10)
    if resp.status_code == 204:
        return "Nothing is currently playing on Spotify."
    if not resp.ok:
        return f"Spotify error {resp.status_code}: {resp.text[:120]}"
    data = resp.json()
    item = data.get("item")
    if not item:
        return "Nothing is currently playing."
    track  = item.get("name", "Unknown")
    artist = ", ".join(a["name"] for a in item.get("artists", [])) or "Unknown"
    is_playing = data.get("is_playing", False)
    status = "Playing" if is_playing else "Paused"
    return f"{status}: {track} by {artist}."


def _play_song(params: dict) -> str:
    query = str(params.get("query", "")).strip()
    if not query:
        return "Please specify a song to search for."
    result = _search(query, "track")
    if not result:
        return f"Couldn't search for '{query}'."
    tracks = result.get("tracks", {}).get("items", [])
    if not tracks:
        return f"No tracks found for '{query}'."
    track = tracks[0]
    uri   = track["uri"]
    name  = track["name"]
    artist = ", ".join(a["name"] for a in track.get("artists", []))
    err = _player_put("/me/player/play", {"uris": [uri]})
    return err or f"Playing {name} by {artist}."


def _play_artist(params: dict) -> str:
    query = str(params.get("query", "")).strip()
    if not query:
        return "Please specify an artist to play."
    result = _search(query, "artist")
    if not result:
        return f"Couldn't search for '{query}'."
    artists = result.get("artists", {}).get("items", [])
    if not artists:
        return f"No artist found for '{query}'."
    artist = artists[0]
    uri    = artist["uri"]
    name   = artist["name"]
    err = _player_put("/me/player/play", {"context_uri": uri})
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
    err = _no_device_msg(resp)
    if err:
        return err
    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:120]}"
    return f"Volume set to {level}%."


# ── dispatch ─────────────────────────────────────────────────────────────────

_ACTIONS = {
    "play":          _play,
    "pause":         _pause,
    "next":          _next_track,
    "previous":      _previous_track,
    "what_playing":  _what_playing,
    "play_song":     _play_song,
    "play_artist":   _play_artist,
    "volume":        _set_volume,
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
    except requests.exceptions.ConnectionError:
        return "Couldn't reach Spotify. Check your internet connection."
    except requests.exceptions.Timeout:
        return "Spotify request timed out."
    except Exception as e:
        return f"Spotify error: {e}"
