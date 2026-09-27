"""Import worker results from the inbox into durable, write-once storage (AC-D05, D07, D08)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from delivery.store import Store


@dataclass
class ImportOutcome:
    status: str  # imported | duplicate | conflict | rejected
    state: dict[str, Any]
    ref: str | None = None
    reasons: list[str] = field(default_factory=list)


def import_result(store: Store, state: dict[str, Any], assignment: dict[str, Any], inbox_file: Path) -> ImportOutcome:
    raise NotImplementedError
