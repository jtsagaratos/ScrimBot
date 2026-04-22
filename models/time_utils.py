import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import pytz


TIMEZONE_ALIASES = {
    "EST": "US/Eastern",
    "EDT": "US/Eastern",
    "ET": "US/Eastern",
    "CST": "US/Central",
    "CDT": "US/Central",
    "CT": "US/Central",
    "MST": "US/Mountain",
    "MDT": "US/Mountain",
    "MT": "US/Mountain",
    "PST": "US/Pacific",
    "PDT": "US/Pacific",
    "PT": "US/Pacific",
    "UTC": "UTC",
    "GMT": "UTC",
}

COMMON_TIMEZONES = [
    "US/Eastern",
    "US/Central",
    "US/Mountain",
    "US/Pacific",
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
]

TIMEZONE_PATTERN = re.compile(
    r"\s+(EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|PST|PDT|PT|UTC|GMT|[A-Za-z]+/[A-Za-z_]+)$",
    re.IGNORECASE,
)


def normalize_timezone(timezone_name: Optional[str], default: str = "US/Eastern") -> str:
    """Return a valid pytz timezone name from an alias or IANA timezone."""
    if not timezone_name:
        timezone_name = default

    candidate = timezone_name.strip()
    alias = TIMEZONE_ALIASES.get(candidate.upper())
    if alias:
        return alias

    if candidate in pytz.all_timezones:
        return candidate

    raise ValueError(
        f"Unknown timezone '{timezone_name}'. Use an abbreviation like EST/PST/UTC "
        "or an IANA timezone like America/Denver."
    )


def split_trailing_timezone(text: str) -> Tuple[str, Optional[str]]:
    """Split a trailing timezone token from a date string, if one is present."""
    match = TIMEZONE_PATTERN.search(text.strip())
    if not match:
        return text.strip(), None
    timezone_name = match.group(1)
    return TIMEZONE_PATTERN.sub("", text.strip()).strip(), timezone_name


def localize_datetime(dt: datetime, timezone_name: str) -> datetime:
    """Attach or convert a datetime to the requested timezone."""
    tz = pytz.timezone(timezone_name)
    if dt.tzinfo is None:
        return tz.localize(dt)
    return dt.astimezone(tz)


def to_utc_iso(dt: datetime) -> str:
    """Store datetimes as timezone-aware UTC ISO strings."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def validate_duration_hours(duration_hours) -> float:
    """Validate a Discord event duration entered as hours."""
    try:
        duration = float(duration_hours)
    except (TypeError, ValueError):
        raise ValueError("Duration hours must be a number.")

    if duration <= 0:
        raise ValueError("Duration hours must be greater than 0.")
    if duration > 24:
        raise ValueError("Duration hours must be 24 or less.")
    return duration


def event_end_time(start_time: datetime, duration_hours) -> datetime:
    """Return an event end time based on a validated hour duration."""
    duration = validate_duration_hours(duration_hours)
    return start_time + timedelta(minutes=round(duration * 60))


def parse_stored_datetime(value: str) -> datetime:
    """Parse stored ISO strings and normalize to UTC."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_for_timezone(value: str, timezone_name: str) -> str:
    """Format a stored UTC ISO datetime for a display timezone."""
    dt = parse_stored_datetime(value).astimezone(pytz.timezone(timezone_name))
    return dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")


def discord_timestamp(value, style: str = "F") -> str:
    """Return a Discord native timestamp that renders in each user's timezone."""
    if isinstance(value, str):
        dt = parse_stored_datetime(value)
    else:
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    return f"<t:{int(dt.timestamp())}:{style}>"


def discord_time_display(value, timezone_name: str) -> str:
    """Show the scheduled timezone and Discord's per-user local timestamp."""
    return (
        f"{format_for_timezone(value, timezone_name)}\n"
        f"Local: {discord_timestamp(value, 'F')} ({discord_timestamp(value, 'R')})"
    )
