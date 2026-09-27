"""Bindings/observations, VersionSet, dependency matrix and assessment derivation (design §5, DR-02/03/10)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

GATES = ("g1", "g2", "g3")
ROLES = ("project_spec", "feature_spec", "issue_body", "design", "plan", "validation", "policy")
KNOWN_SKILLS = ("superpowers:test-driven-development", "openspec-apply-change")

Evaluator = Callable[[dict[str, Any], dict[str, Any]], tuple[str, list[str]]]


class DecisionRejected(ValueError):
    pass


def version_key(vs: dict[str, Any]) -> str:
    raise NotImplementedError


def matrix_rows() -> dict[str, dict[str, str]]:
    raise NotImplementedError


def observe_binding(state: dict[str, Any], role: str, locator: str, content: bytes, now: str) -> str:
    raise NotImplementedError


def adopt_binding(state: dict[str, Any], decision: dict[str, Any]) -> None:
    raise NotImplementedError


def version_set(state: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def derive(assessment: dict[str, Any], old_vs: dict[str, Any], new_vs: dict[str, Any],
           reevaluate: Evaluator | None = None, base_recheck: dict[str, Any] | None = None) -> dict[str, Any]:
    raise NotImplementedError
