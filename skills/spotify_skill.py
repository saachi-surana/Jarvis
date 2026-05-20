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
            "Please complete the Spotify OAuth flow first."
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
    if "refresh_token" not in new_token:
        new_token["refresh_token"] = refresh_token
    # expires_at is stored in milliseconds
    new_token["expires_at"] = int(time.time() * 1000) + new_token.get("expires_in", 3600) * 1000
    _save_token(new_token)
    print("[Spotify] Token refreshed successfully.")
    return new_token


def _get_headers() -> dict:
    cfg   = _load_config()
    token = _load_token()
    # expires_at is a millisecond timestamp; refresh 60 seconds early
    if time.time() * 1000 >= token.get("expires_at", 0) - 60_000:
        print("[Spotify] Token expired or expiring soon — refreshing.")
        token = _refresh_access_token(cfg, token)
    return {"Authorization": f"Bearer {token['access_token']}"}


# ── device recovery ──────────────────────────────────────────────────────────

def _poll_for_device(max_attempts: int = 5, interval: float = 1.0) -> str | None:
    """Poll /me/player/devices until a device appears. Returns device_id or None."""
    for attempt in range(max_attempts):
        try:
            resp = requests.get(f"{API_BASE}/me/player/devices", headers=_get_headers(), timeout=10)
            print(f"[Spotify] Devices poll attempt {attempt + 1}: status={resp.status_code}")
            if resp.ok:
                devices = resp.json().get("devices", [])
                print(f"[Spotify] Devices found: {[d.get('name') for d in devices]}")
                if devices:
                    # Prefer already-active device
                    for d in devices:
                        if d.get("is_active"):
                            print(f"[Spotify] Using active device: {d['name']} ({d['id']})")
                            return d["id"]
                    print(f"[Spotify] Using first available device: {devices[0]['name']} ({devices[0]['id']})")
                    return devices[0]["id"]
        except Exception as e:
            print(f"[Spotify] Device poll error: {e}")
        if attempt < max_attempts - 1:
            time.sleep(interval)
    return None


def _open_spotify_and_get_device() -> str | None:
    """Launch Spotify, wait for it to register a device, return device_id."""
    print("[Spotify] No active device — launching Spotify app.")
    subprocess.Popen(["open", "-a", "Spotify"])
    time.sleep(4)  # give Spotify time to fully start
    return _poll_for_device(max_attempts=5, interval=1.0)


# ── low-level request helpers ────────────────────────────────────────────────

def _player_put(path: str, body: dict | None = None, device_id: str | None = None) -> str | None:
    """PUT to Spotify player API. Returns error string or None on success."""
    headers = _get_headers()
    headers["Content-Type"] = "application/json"
    params  = {"device_id": device_id} if device_id else {}
    url     = f"{API_BASE}{path}"

    resp = requests.put(url, headers=headers, json=body or {}, params=params, timeout=10)
    print(f"[Spotify] PUT {path} device_id={device_id} → {resp.status_code}: {resp.text[:200]}")

    if resp.status_code in (404, 403) and not device_id:
        recovered_id = _open_spotify_and_get_device()
        if not recovered_id:
            return "Spotify launched but no device appeared — please try again in a moment."
        # Retry with device_id
        retry_h = _get_headers()
        retry_h["Content-Type"] = "application/json"
        resp2 = requests.put(url, headers=retry_h, json=body or {},
                             params={"device_id": recovered_id}, timeout=10)
        print(f"[Spotify] PUT retry device_id={recovered_id} → {resp2.status_code}: {resp2.text[:200]}")
        if resp2.status_code not in (200, 204):
            return f"Spotify error {resp2.status_code}: {resp2.text[:200]}"
        return None

    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:200]}"
    return None


def _player_post(path: str, device_id: str | None = None) -> str | None:
    """POST to Spotify player API. Returns error string or None on success."""
    headers = _get_headers()
    params  = {"device_id": device_id} if device_id else {}
    url     = f"{API_BASE}{path}"

    resp = requests.post(url, headers=headers, params=params, timeout=10)
    print(f"[Spotify] POST {path} device_id={device_id} → {resp.status_code}: {resp.text[:200]}")

    if resp.status_code in (404, 403) and not device_id:
        recovered_id = _open_spotify_and_get_device()
        if not recovered_id:
            return "Spotify launched but no device appeared — please try again in a moment."
        resp2 = requests.post(url, headers=_get_headers(), params={"device_id": recovered_id}, timeout=10)
        print(f"[Spotify] POST retry device_id={recovered_id} → {resp2.status_code}: {resp2.text[:200]}")
        if resp2.status_code not in (200, 204):
            return f"Spotify error {resp2.status_code}: {resp2.text[:200]}"
        return None

    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:200]}"
    return None


def _play_with_device(path: str, body: dict) -> str | None:
    """
    Try to play. If no active device, open Spotify, get a device, then
    transfer playback to that device first, then send the play command.
    Returns error string or None on success.
    """
    headers = _get_headers()
    headers["Content-Type"] = "application/json"

    resp = requests.put(f"{API_BASE}{path}", headers=headers, json=body, timeout=10)
    print(f"[Spotify] play attempt → {resp.status_code}: {resp.text[:200]}")

    if resp.status_code in (200, 204):
        return None

    if resp.status_code in (404, 403):
        device_id = _open_spotify_and_get_device()
        if not device_id:
            return "Spotify launched but no device appeared — please try again in a moment."

        # Transfer playback to the device so it becomes active
        transfer_resp = requests.put(
            f"{API_BASE}/me/player",
            headers={"Authorization": _get_headers()["Authorization"], "Content-Type": "application/json"},
            json={"device_ids": [device_id], "play": False},
            timeout=10,
        )
        print(f"[Spotify] Transfer playback → {transfer_resp.status_code}: {transfer_resp.text[:200]}")
        time.sleep(1)  # brief pause after transfer

        # Now send the actual play command with device_id
        final_headers = _get_headers()
        final_headers["Content-Type"] = "application/json"
        final_resp = requests.put(
            f"{API_BASE}{path}",
            headers=final_headers,
            json=body,
            params={"device_id": device_id},
            timeout=10,
        )
        print(f"[Spotify] play with device_id={device_id} → {final_resp.status_code}: {final_resp.text[:200]}")
        if final_resp.status_code not in (200, 204):
            return f"Spotify error {final_resp.status_code}: {final_resp.text[:200]}"
        return None

    return f"Spotify error {resp.status_code}: {resp.text[:200]}"


def _search(query: str, search_type: str) -> dict | None:
    resp = requests.get(
        f"{API_BASE}/search",
        headers=_get_headers(),
        params={"q": query, "type": search_type, "limit": 3},
        timeout=10,
    )
    print(f"[Spotify] search type={search_type} q={query!r} → {resp.status_code}")
    if not resp.ok:
        print(f"[Spotify] search error: {resp.text[:200]}")
        return None
    return resp.json()


# ── actions ──────────────────────────────────────────────────────────────────

def _play(params: dict) -> str:
    err = _play_with_device("/me/player/play", {})
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
    print(f"[Spotify] currently-playing → {resp.status_code}")
    if resp.status_code == 204:
        return "Nothing is currently playing on Spotify."
    if not resp.ok:
        return f"Spotify error {resp.status_code}: {resp.text[:200]}"
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
    print(f"[Spotify] play_song: {name} by {artist} ({uri})")

    err = _play_with_device("/me/player/play", {"uris": [uri]})
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
        # Fallback: try playing a track by this name instead
        print(f"[Spotify] No artist found for {query!r} — falling back to track search.")
        return _play_song(params)

    artist    = artists[0]
    artist_id = artist["id"]
    name      = artist["name"]
    context_uri = f"spotify:artist:{artist_id}"
    print(f"[Spotify] play_artist: {name} ({context_uri})")

    err = _play_with_device("/me/player/play", {"context_uri": context_uri})
    if err:
        # Fallback: play top track by this artist directly
        print(f"[Spotify] context_uri play failed ({err}), trying top tracks fallback.")
        top_resp = requests.get(
            f"{API_BASE}/artists/{artist_id}/top-tracks",
            headers=_get_headers(),
            params={"market": "US"},
            timeout=10,
        )
        print(f"[Spotify] top-tracks → {top_resp.status_code}: {top_resp.text[:200]}")
        if top_resp.ok:
            tracks = top_resp.json().get("tracks", [])
            if tracks:
                uris = [f"spotify:track:{t['id']}" for t in tracks[:5]]
                err2 = _play_with_device("/me/player/play", {"uris": uris})
                if not err2:
                    return f"Playing {name}."
        return err  # return original error if both attempts fail

    return f"Playing {name}."


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
    print(f"[Spotify] volume={level} → {resp.status_code}: {resp.text[:200]}")

    if resp.status_code in (404, 403):
        device_id = _open_spotify_and_get_device()
        if not device_id:
            return "Spotify launched but no device appeared — please try again in a moment."
        resp2 = requests.put(
            f"{API_BASE}/me/player/volume",
            headers=_get_headers(),
            params={"volume_percent": level, "device_id": device_id},
            timeout=10,
        )
        print(f"[Spotify] volume retry device_id={device_id} → {resp2.status_code}: {resp2.text[:200]}")
        if resp2.status_code not in (200, 204):
            return f"Spotify error {resp2.status_code}: {resp2.text[:200]}"
        return f"Volume set to {level}%."

    if resp.status_code not in (200, 204):
        return f"Spotify error {resp.status_code}: {resp.text[:200]}"
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
    print(f"[Spotify] execute action={action!r}")
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
        return f"Missing Spotify config key: {e}"
    except requests.exceptions.ConnectionError:
        return "Couldn't reach Spotify — check your internet connection."
    except requests.exceptions.Timeout:
        return "Spotify request timed out."
    except Exception as e:
        import traceback
        print(f"[Spotify] Unexpected error:\n{traceback.format_exc()}")
        return f"Spotify error: {e}"
