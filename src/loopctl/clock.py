"""The single clock. Call as `clock.now()` so tests can monkeypatch it in-process."""

from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)
