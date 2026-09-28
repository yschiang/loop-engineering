"""Git reads and the bounded evidence command (design §7, §8; T3.1).

Every git call here is read-only on history except the two G1 needs: a snapshot commit with
its keep-alive ref (`evidence red`), and the temporary detached checkout of `evidence green` /
replay (`worktree add --detach`, removed afterwards). The evidence command runs in its own
process group and the whole group is killed at the time limit.
"""

from pathlib import Path
from typing import Any


class GitError(Exception):
    pass


def toplevel(cwd: Path, timeout_s: float) -> str | None:
    raise NotImplementedError


def rev_parse(repo: str, rev: str, timeout_s: float) -> str | None:
    raise NotImplementedError


def run_command(argv: list[str], cwd: str, timeout_s: float) -> dict[str, Any]:
    raise NotImplementedError
