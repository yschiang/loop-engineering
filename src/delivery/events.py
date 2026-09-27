"""events.jsonl audit history with pending-history recovery (design §8, AC-D10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from delivery.store import Store, StoreError


class EventConflict(StoreError):
    pass


@dataclass
class RecoverResult:
    blocked: bool
    reasons: list[str] = field(default_factory=list)
    diagnostic: Path | None = None


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def recover(self) -> RecoverResult:
        raise NotImplementedError

    def append(self, events: list[dict[str, Any]]) -> list[str]:
        raise NotImplementedError


def flush_pending(store: Store, log: EventLog) -> RecoverResult:
    raise NotImplementedError
