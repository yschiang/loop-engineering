"""Durable blobs, atomic run snapshots and reference integrity (design §8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class StoreError(Exception):
    """Base class; every subclass means the state is not trusted and dispatch must stop."""


class StateMissing(StoreError):
    pass


class StateCorrupt(StoreError):
    pass


class SchemaMismatch(StoreError):
    pass


class BlobConflict(StoreError):
    pass


class NotDurable(StoreError):
    pass


class ManualEditDetected(StoreError):
    pass


@dataclass(frozen=True)
class BlobHandle:
    ref: str  # "sha256:<hex>"
    path: Path


@dataclass
class LoadResult:
    state: dict[str, Any]
    blocked: bool
    reasons: list[str] = field(default_factory=list)


class Store:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def put_blob(self, data: bytes, name: str | None = None) -> BlobHandle:
        raise NotImplementedError

    def commit(self, state: dict[str, Any]) -> int:
        raise NotImplementedError

    def load(self) -> LoadResult:
        raise NotImplementedError
