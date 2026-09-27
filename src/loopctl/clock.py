"""The single clock. Call as `clock.now()` so tests can monkeypatch it in-process."""

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)
