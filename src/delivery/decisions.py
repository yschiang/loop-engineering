"""Human decisions and acceptance bound to versions (design §4, D03/D11/D19)."""

from __future__ import annotations

from typing import Any


class DecisionInvalid(ValueError):
    pass


def apply_decision(state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def may_dispatch_implementation(state: dict[str, Any]) -> bool:
    raise NotImplementedError


def acceptance_for(state: dict[str, Any], version_key: str) -> str:
    raise NotImplementedError
