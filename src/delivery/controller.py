"""Feature phase routing and dispatch guards (design §3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def route_intake(facts: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def authorize_dispatch(state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def dependency_ready(dep: dict[str, Any], is_ancestor: Callable[[str, str], bool], baseline: str) -> dict[str, Any]:
    raise NotImplementedError


def mark_cross_feature_impact(state: dict[str, Any], task_ids: list[str], impact: str) -> None:
    raise NotImplementedError
