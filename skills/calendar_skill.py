import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CONFIG_PATH = os.path.expanduser("~/.notion-planner/config.json")
TOKEN_PATH  = os.path.expanduser("~/.notion-planner/google-token.json")
SCOPES      = ["https://www.googleapis.com/auth/calendar.events"]


def _load_credentials():
    from google.oauth2.credentials import Credentials

    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError(f"Google config not found: {CONFIG_PATH}")
    if not os.path.isfile(TOKEN_PATH):
        raise FileNotFoundError(f"Google token not found: {TOKEN_PATH}")

    config = json.load(open(CONFIG_PATH))
    token  = json.load(open(TOKEN_PATH))

    return Credentials(
        token=token["access_token"],
        refresh_token=token["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config["googleClientId"],
        client_secret=config["googleClientSecret"],
        scopes=SCOPES,
    )


def _build_service():
    from googleapiclient.discovery import build
    creds = _load_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _local_midnight(date: datetime) -> datetime:
    local_tz = datetime.now().astimezone().tzinfo
    return date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=local_tz)


def _fetch_events(service, time_min: datetime, time_max: datetime) -> list:
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        )
        .execute()
    )
    return result.get("items", [])


def _parse_event_start(event: dict) -> datetime | None:
    start = event.get("start", {})
    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"])
    return None  # all-day event


def _format_duration(start: datetime, end_raw: dict) -> str:
    if "dateTime" not in end_raw:
        return "all day"
    end = datetime.fromisoformat(end_raw["dateTime"])
    total_minutes = int((end - start).total_seconds() // 60)
    if total_minutes < 60:
        return f"{total_minutes} min"
    hours = total_minutes // 60
    mins  = total_minutes % 60
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours}h {mins}m"


def _format_event(event: dict, include_date: bool = False) -> str:
    title     = event.get("summary", "Untitled event")
    start_raw = event.get("start", {})
    end_raw   = event.get("end", {})

    if "dateTime" in start_raw:
        start_dt = datetime.fromisoformat(start_raw["dateTime"])
        time_str = start_dt.strftime("%-I:%M %p").lstrip("0") or "12:00 AM"
        duration = _format_duration(start_dt, end_raw)
        line = f"{time_str} — {title} ({duration})"
    else:
        line = f"All day — {title}"

    if include_date:
        date_label = datetime.fromisoformat(
            start_raw.get("dateTime", start_raw.get("date", ""))[:10]
        ).strftime("%A, %b %-d")
        line = f"{date_label}: {line}"

    return line


def _friendly_list(events: list, label: str, include_date: bool = False) -> str:
    if not events:
        return f"Nothing on your calendar {label}."
    lines = [_format_event(e, include_date=include_date) for e in events]
    return f"Here's what you have {label}:\n" + "\n".join(f"  • {l}" for l in lines)


def _create_event(service, params: dict) -> str:
    title       = str(params.get("title", "")).strip()
    date_str    = str(params.get("date", "")).strip()
    start_time  = str(params.get("start_time", "")).strip()
    end_time    = str(params.get("end_time", "")).strip()
    description = str(params.get("description", "")).strip()

    if not title or not date_str or not start_time or not end_time:
        return "Please provide title, date, start_time, and end_time to create an event."

    local_tz = datetime.now().astimezone().tzinfo
    try:
        start_dt = datetime.fromisoformat(f"{date_str}T{start_time}").replace(tzinfo=local_tz)
        end_dt   = datetime.fromisoformat(f"{date_str}T{end_time}").replace(tzinfo=local_tz)
    except ValueError as e:
        return f"Invalid date/time format: {e}"

    body: dict = {
        "summary": title,
        "start":   {"dateTime": start_dt.isoformat(), "timeZone": str(local_tz)},
        "end":     {"dateTime": end_dt.isoformat(),   "timeZone": str(local_tz)},
    }
    if description:
        body["description"] = description

    service.events().insert(calendarId="primary", body=body).execute()

    friendly_date = start_dt.strftime("%A, %b %-d")
    friendly_start = start_dt.strftime("%-I:%M %p")
    friendly_end   = end_dt.strftime("%-I:%M %p")
    return f"Added '{title}' on {friendly_date} from {friendly_start} to {friendly_end}."


def execute(params: dict) -> str:
    try:
        service = _build_service()
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't connect to Google Calendar: {e}"

    if params.get("action") == "create":
        try:
            return _create_event(service, params)
        except Exception as e:
            return f"Calendar error creating event: {e}"

    query = str(params.get("query", "today")).strip().lower()
    now   = datetime.now().astimezone()

    try:
        if query == "today":
            start  = _local_midnight(now)
            events = _fetch_events(service, start, start + timedelta(days=1))
            return _friendly_list(events, "today")

        if query == "tomorrow":
            start  = _local_midnight(now) + timedelta(days=1)
            events = _fetch_events(service, start, start + timedelta(days=1))
            return _friendly_list(events, "tomorrow")

        if query == "next_event":
            events = _fetch_events(service, now, now + timedelta(days=30))
            if not events:
                return "No upcoming events in the next 30 days."
            return f"Your next event: {_format_event(events[0], include_date=True)}"

        if query == "week":
            start  = _local_midnight(now)
            events = _fetch_events(service, start, start + timedelta(days=7))
            return _friendly_list(events, "this week", include_date=True)

        # Unrecognised query — try to guess intent, default to today
        if "tomorrow" in query:
            start  = _local_midnight(now) + timedelta(days=1)
            events = _fetch_events(service, start, start + timedelta(days=1))
            return _friendly_list(events, "tomorrow")
        if "week" in query:
            start  = _local_midnight(now)
            events = _fetch_events(service, start, start + timedelta(days=7))
            return _friendly_list(events, "this week", include_date=True)
        if "next" in query:
            events = _fetch_events(service, now, now + timedelta(days=30))
            if not events:
                return "No upcoming events in the next 30 days."
            return f"Your next event: {_format_event(events[0], include_date=True)}"
        # Default: today
        start  = _local_midnight(now)
        events = _fetch_events(service, start, start + timedelta(days=1))
        return _friendly_list(events, "today")

    except Exception as e:
        return f"Calendar error: {e}"
