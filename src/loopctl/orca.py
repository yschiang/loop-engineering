"""Orca, the transport: its fixed argv and the parsing of its JSON (design
DD-1, DD-4). No function takes a command from its caller (ORC-01).

No function reaches Orca: each answers Problem("transport_missing"), the
answer for an Orca that cannot be used, on which no probe goes on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class Problem:
    """Why an Orca call gave no usable answer: `transport_missing`,
    `timeout`, `unparseable:<command>`, `exit:<n>`, and for worker_start
    `failed_stage:<stage>`. A value, never raised."""

    reason: str


@dataclass(frozen=True)
class Started:
    """The Task and the Dispatch of a worker Orca accepted."""

    task: str
    dispatch: str


MISSING = Problem("transport_missing")


def version() -> str | Problem:
    return MISSING


def status() -> dict[str, Any] | Problem:
    return MISSING


def run_current() -> str | None | Problem:
    return MISSING


def run_create(objective: str) -> str | Problem:
    return MISSING


def repos() -> list[dict[str, Any]] | Problem:
    return MISSING


def worktrees() -> list[dict[str, Any]] | Problem:
    return MISSING


def terminal_create(worktree_id: str, title: str, command: str) -> str | Problem:
    return MISSING


def worker_start(
    spec: str, terminal: str, worktree_id: str, run: str
) -> Started | Problem:
    return MISSING


def worker_show(dispatch: str) -> dict[str, Any] | Problem:
    return MISSING


def terminal_wait(handle: str, timeout_ms: int) -> Literal["idle", "timeout"] | Problem:
    return MISSING


def terminal_close(handle: str) -> bool | Problem:
    return MISSING


def task_list(run: str) -> list[dict[str, Any]] | Problem:
    return MISSING
