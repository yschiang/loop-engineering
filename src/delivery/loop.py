"""Controller main loop: one persisted transition per step (design §3, §9.2, §11)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Context:
    run_dir: Path
    ctl_repo: Path
    attempts_root: Path
    branch: str
    runtime: Any
    github: Any
    policy: dict[str, Any]
    isolation: dict[str, Any] | None
    sandbox_profile_digest: str | None


def start_run(ctx: Context, run_id: str, feature_key: str, tasks: list[dict[str, Any]], plan_version: str,
              bindings: dict[str, str], approval: dict[str, Any] | None) -> dict[str, Any]:
    raise NotImplementedError


def step(ctx: Context) -> str:
    raise NotImplementedError


def run_until_idle(ctx: Context, max_steps: int = 200) -> list[str]:
    raise NotImplementedError
