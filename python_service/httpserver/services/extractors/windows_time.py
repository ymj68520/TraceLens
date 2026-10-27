"""Lossless source ticks and explicit UTC conversion for Windows artifacts."""
from datetime import datetime, timedelta, timezone

FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def filetime_to_datetime(value: int) -> datetime | None:
    if not isinstance(value, int) or value <= 0 or value > 0x7fffffffffffffff:
        return None
    try:
        # datetime supports microseconds; callers retain the original 100 ns ticks.
        return FILETIME_EPOCH + timedelta(microseconds=value // 10)
    except (OverflowError, ValueError):
        return None


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
