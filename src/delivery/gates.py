"""Deterministic gate evaluators (design §6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

IsAncestor = Callable[[str, str], bool]


def evaluate_g1(tasks: list[dict[str, Any]], green: dict[str, Any] | None, head: str,
                is_ancestor: IsAncestor) -> dict[str, Any]:
    raise NotImplementedError
