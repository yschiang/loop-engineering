"""Review publication content and human-readable status (AC-F13, F14, D01)."""

from __future__ import annotations

from typing import Any


def register_publication(state: dict[str, Any], run_id: str, review: dict[str, Any]) -> tuple[str, str]:
    raise NotImplementedError


def publication_status(state: dict[str, Any], op_ids: tuple[str, str]) -> str:
    raise NotImplementedError


def render_status(state: dict[str, Any]) -> str:
    raise NotImplementedError
