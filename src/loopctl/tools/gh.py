"""GitHub and remote-git calls (T6.1): the `push` / `pr_ensure` op calls and their readbacks,
and the bounded reads of `observe pr|ci` (design §4, §5, §8).

Interface stub: the functions are filled in by the T6.1 implementation commit.
"""

from typing import Any


class ReadFailed(Exception):
    """A transport failure of a read (time limit, lost client, 5xx, unparseable reply, a page)."""

    def __init__(self, reason: str, raw: str = "") -> None:
        super().__init__(reason)
        self.reason, self.raw = reason, raw


def op_call(kind: str, argv: Any, timeout_s: float, expected: dict[str, Any], read_s: float) -> dict[str, Any]:
    raise NotImplementedError(kind)


def readback(kind: str, expected: dict[str, Any], timeout_s: float, observed: str | None = None) -> dict[str, Any]:
    raise NotImplementedError(kind)


def read_pr(repo: str, number: int, timeout_s: float) -> tuple[dict[str, Any], str]:
    raise NotImplementedError(repo)


def read_ci(repo: str, head: str, base: str, workflow: str, names: list[str], timeout_s: float) -> tuple[dict[str, Any], str]:
    raise NotImplementedError(repo)
