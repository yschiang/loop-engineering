"""Host-level feature authority locator, run lineage and feature budget (design §9.1, DR-06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StartOutcome:
    status: str  # created | resume | refused | blocked
    run_id: str | None = None
    state_dir: str | None = None
    repo_path: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class Budget:
    blocked: bool
    correction_rounds_used: int = 0
    active_seconds: float = 0.0
    reasons: list[str] = field(default_factory=list)


def feature_id(repo_id: str, feature_key: str) -> str:
    raise NotImplementedError


class Authority:
    def __init__(self, state_home: Path, repo_id: str, feature_key: str) -> None:
        self.state_home = state_home
        self.repo_id = repo_id
        self.feature_key = feature_key

    def start(self, repo_path: str, state_dir: str, run_id: str) -> StartOutcome:
        raise NotImplementedError

    def abandon(self, run_id: str, decision: dict[str, Any]) -> None:
        raise NotImplementedError

    def budget(self) -> Budget:
        raise NotImplementedError

    def repair_project_view(self, repo_path: str) -> Path:
        raise NotImplementedError
