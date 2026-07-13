from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Europe/Moscow"


def resolved_zoneinfo(timezone_name: str | None) -> tuple[str, ZoneInfo]:
    value = timezone_name or DEFAULT_TIMEZONE
    try:
        return value, ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_TIMEZONE, ZoneInfo(DEFAULT_TIMEZONE)
