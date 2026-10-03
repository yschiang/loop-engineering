"""Bounded subprocesses: the one place loopctl starts a program (design
DD-1, ORC-01). Every argv is built by loopctl, never taken from a caller
or a worker."""

from __future__ import annotations

import re
import subprocess
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
    """Run `argv`, found on PATH, with no input, until it ends or
    `timeout_s` passes; then it is killed. Never raises: a program that
    cannot be started is `missing`, and output that is not UTF-8 is read
    with replacement characters."""
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as error:
        return Completed(None, _text(error.stdout), _text(error.stderr), "timeout")
    except OSError:
        return Completed(None, "", "", "missing")
    return Completed(done.returncode, done.stdout, done.stderr, "ok")


def _text(output: str | bytes | None) -> str:
    """What a stopped program wrote; TimeoutExpired keeps it as bytes."""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output or ""


def failure(done: Completed) -> str | None:
    """Why `done` has no output to read: `missing`, `timeout` or
    `exit:<n>`; None when the program ran and exited 0."""
    if done.status != "ok":
        return done.status
    return None if done.code == 0 else f"exit:{done.code}"


VERSION = re.compile(r"\d+(?:\.\d+)+")


def version(text: str) -> str | None:
    """The version in what a program prints, the first dotted number:
    `1.4.218`, `2.1.288 (Claude Code)`, `codex-cli 0.157.0` (DD-9)."""
    found = VERSION.search(text)
    return found[0] if found else None
