"""Finding registry: stable IDs, blocking rules and closure authority (design §7, D09/D12/D24)."""

from __future__ import annotations

from typing import Any


class ClosureRejected(ValueError):
    pass


def import_review(registry: dict[str, Any], review: dict[str, Any], version_key: str) -> list[str]:
    raise NotImplementedError


def submit_fix(registry: dict[str, Any], fid: str, commit: str, evidence: list[str]) -> None:
    raise NotImplementedError


def record_external(registry: dict[str, Any], fid: str, event: dict[str, Any]) -> None:
    raise NotImplementedError


def close(registry: dict[str, Any], fid: str, closure: dict[str, Any], current_key: str) -> None:
    raise NotImplementedError


def open_blocking(registry: dict[str, Any]) -> list[str]:
    raise NotImplementedError
