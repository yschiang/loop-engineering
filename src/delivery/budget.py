"""Active-time budget, crash unknown intervals and failure routing (design §12, D13)."""

from __future__ import annotations

from typing import Any

ACTIVE_LIMIT_SECONDS = 4 * 3600  # D13


def open_activity(budget: dict[str, Any], activity_id: str, kind: str, now: float) -> None:
    raise NotImplementedError


def close_activity(budget: dict[str, Any], activity_id: str, now: float) -> None:
    raise NotImplementedError


def on_resume(budget: dict[str, Any], last_persisted_at: float, resume_at: float,
              external_ends: dict[str, float | None]) -> None:
    raise NotImplementedError


def active_seconds(budget: dict[str, Any], now: float) -> float:
    raise NotImplementedError


def may_dispatch(budget: dict[str, Any], now: float) -> bool:
    raise NotImplementedError


def failure_route(kind: str) -> str:
    raise NotImplementedError
