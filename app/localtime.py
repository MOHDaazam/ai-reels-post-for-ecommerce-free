"""Local-time formatting for logs and timestamps shown in the studio.

Datetimes are stored as UTC. Everything a person reads is rendered in the
machine's local zone, or in APP_TIMEZONE when it is set.
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings

LOG_FORMAT = "%Y-%m-%d %H:%M:%S %Z"
DISPLAY_FORMAT = "%Y-%m-%d %H:%M"
_LEGACY_UTC_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


def local_zone() -> tzinfo:
    name = (settings.app_timezone or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def to_local(value: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone-aware columns.
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(local_zone())


def now_local() -> datetime:
    return datetime.now(local_zone())


def stamp(value: datetime | None = None) -> str:
    moment = now_local() if value is None else to_local(value)
    return moment.strftime(LOG_FORMAT).strip()


def isoformat(value: datetime | None = None) -> str:
    return (now_local() if value is None else to_local(value)).isoformat()


def parse_log_stamp(line: str) -> datetime | None:
    """Read the bracketed prefix of a log line, old UTC lines included."""
    if not line.startswith("[") or "]" not in line:
        return None
    raw = line[1 : line.index("]")].strip()
    try:
        return datetime.strptime(raw, _LEGACY_UTC_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        # Zone abbreviations are ambiguous, but the studio writes local time.
        naive = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=local_zone())


def display(value: datetime | str | None) -> str:
    if value is None:
        return ""
    moment = value
    if isinstance(moment, str):
        try:
            moment = datetime.fromisoformat(moment)
        except ValueError:
            return value if isinstance(value, str) else ""
    return to_local(moment).strftime(DISPLAY_FORMAT)
