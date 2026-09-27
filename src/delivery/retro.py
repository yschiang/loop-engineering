"""Retro candidate operation after human acceptance, and the P03 guard (D22/D28)."""

from __future__ import annotations

from typing import Any


def register_retro(state: dict[str, Any], acceptance: dict[str, Any]) -> str | None:
    raise NotImplementedError


def may_start_trial(state: dict[str, Any], feature: str) -> bool:
    raise NotImplementedError
