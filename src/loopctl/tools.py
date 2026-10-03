"""Bounded subprocesses: the one place loopctl starts a program (design
DD-1, ORC-01). Every argv is built by loopctl, never taken from a caller
or a worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Completed:
    """How a program ended. `code` is None unless it ran to its end:
    `missing` when there is no such program, `timeout` when it was stopped
    at its time limit."""

    code: int | None
    stdout: str
    stderr: str
    status: Literal["ok", "missing", "timeout"]


def run(argv: list[str], timeout_s: float) -> Completed:
    """Never raises. No program is started: every argv is `missing`, the
    answer for a tool that is not there, which no caller takes as output."""
    return Completed(None, "", "", "missing")
