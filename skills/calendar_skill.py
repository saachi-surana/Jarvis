import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TOKEN_PATH = os.path.expanduser("~/.notion-planner/google-token.json")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _load_credentials():
    from google.oauth2.credentials import Credentials
    if not os.path.isfile(TOKEN_PATH):
        raise FileNotFoundError(TOKEN_PATH)
    return Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)


def _build_service():
    from googleapiclient.discovery import build
    creds = _load_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _local_midnight(date: datetime) -> datetime:
    """Return midnight at the start of `date` in local time, as an aware datetime."""
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
    """Return start as an aware datetime, or None for all-day events."""
    start = event.get("start", {})
    if "dateTime" in start:
        return datetime.fromisoformat(start["dateTime"])
    return None  # all-day event


def _format_duration(start: datetime, end_raw: dict) -> str:
    if "dateTime" not in end_raw:
        return "all day"
    end = datetime.fromisoformat(end_raw["dateTime"])
    delta = end - start
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 60:
        return f"{total_minutes} min"
    hours = total_minutes // 60
    mins = total_minutes % 60
    if mins == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours}h {mins}m"


def _format_event(event: dict, include_date: bool = False) -> str:
    title = event.get("summary", "Untitled event")
    start_raw = event.get("start", {})
    end_raw = event.get("end", {})

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
    header = f"Here's what you have {label}:"
    return header + "\n" + "\n".join(f"  • {l}" for l in lines)


def execute(params: dict) -> str:
    try:
        service = _build_service()
    except FileNotFoundError:
        return (
            f"Google Calendar token not found at {TOKEN_PATH}. "
            "Run the notion-planner auth flow to generate it."
        )
    except Exception as e:
        return f"Couldn't connect to Google Calendar: {e}"

    query = str(params.get("query", "today")).strip().lower()
    now = datetime.now().astimezone()

    try:
        if query == "today":
            start = _local_midnight(now)
            end = start + timedelta(days=1)
            events = _fetch_events(service, start, end)
            return _friendly_list(events, "today")

        if query == "tomorrow":
            start = _local_midnight(now) + timedelta(days=1)
            end = start + timedelta(days=1)
            events = _fetch_events(service, start, end)
            return _friendly_list(events, "tomorrow")

        if query == "next_event":
            end = now + timedelta(days=30)
            events = _fetch_events(service, now, end)
            if not events:
                return "No upcoming events in the next 30 days."
            event = events[0]
            formatted = _format_event(event, include_date=True)
            return f"Your next event: {formatted}"

        if query == "week":
            start = _local_midnight(now)
            end = start + timedelta(days=7)
            events = _fetch_events(service, start, end)
            return _friendly_list(events, "this week", include_date=True)

        return f"Unknown calendar query '{query}'. Try: today, tomorrow, next_event, week."

    except Exception as e:
        return f"Calendar error: {e}"
