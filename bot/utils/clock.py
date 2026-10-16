"""Times as the admins read them: stored in UTC, shown in the bot's time zone (TIMEZONE)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(moment: datetime) -> datetime:
    """SQLite hands datetimes back without a zone; they are stored in UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def local(moment: datetime, tz: ZoneInfo) -> datetime:
    return as_utc(moment).astimezone(tz)


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The local day as [start, end) in UTC, for database queries."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def stamp(moment: datetime, tz: ZoneInfo) -> str:
    """16.10.2026 14:05"""
    return f"{local(moment, tz):%d.%m.%Y %H:%M}"


def short_stamp(moment: datetime, tz: ZoneInfo, today: date) -> str:
    """14:05 today, 15.10 18:20 on another day."""
    moment = local(moment, tz)
    return f"{moment:%H:%M}" if moment.date() == today else f"{moment:%d.%m %H:%M}"
