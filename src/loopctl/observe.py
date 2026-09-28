"""Read-only bounded observation (design §5): seq, version watermark, read-failure budget,
and the `worker` / `native` sources (T2.3). T6.1 adds `pr` / `ci` on the same mechanism.
"""

from collections.abc import Callable
from typing import Any

State = dict[str, Any]
SOURCES = ("worker", "native")


class Rejected(Exception):
    def __init__(self, error: str, code: int = 1, **detail: Any) -> None:
        super().__init__(error)
        self.error, self.code, self.detail = error, code, detail


def _not_implemented(*args: Any, **kwargs: Any) -> Any:
    raise Rejected("not_implemented")  # stub (T2.3 interface)


# The fetch per source (a seam: tests reorder reads through it).
FETCHERS: dict[str, Callable[..., Any]] = {"worker": _not_implemented, "native": _not_implemented}


def allocate(feature: str, read_key: str, source: str, purpose: str) -> int:
    return 0  # stub (T2.3 interface)


def commit_fact(
    feature: str,
    seq: int,
    read_key: str,
    purpose: str,
    fact: dict[str, Any],
    raw: str | None,
    versions: dict[str, str] | None = None,
) -> str:
    return "stub"  # stub (T2.3 interface)


def observe(feature: str, token: str | None, source: str, attempt: str, purpose: str | None) -> dict[str, Any]:
    raise Rejected("not_implemented")  # stub (T2.3 interface)


def safety(state: State) -> dict[str, Any] | None:
    return None  # stub (T2.3 interface)
