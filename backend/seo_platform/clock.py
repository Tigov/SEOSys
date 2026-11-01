"""The one source of "now" for the app, so tests can move time forward instead of waiting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_frozen: datetime | None = None


def now() -> datetime:
    return _frozen or datetime.now(timezone.utc)


def set(moment: datetime) -> None:  # noqa: A001 - mirrors the test helper name used across the suite
    global _frozen
    _frozen = moment.astimezone(timezone.utc)


def advance(**delta: float) -> None:
    set(now() + timedelta(**delta))


def reset() -> None:
    global _frozen
    _frozen = None
