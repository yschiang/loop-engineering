"""The one clock of loopctl; tests replace `now` and `sleep` (D13, DD-1)."""

from __future__ import annotations

import datetime
import time


def now() -> str:
    """The current UTC time as ISO 8601."""
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def sleep(seconds: float) -> None:
    """Wait `seconds` before going on."""
    time.sleep(seconds)
