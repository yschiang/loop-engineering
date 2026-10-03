"""Preflight receipts per repo and role, outside the run state, and whether
the latest one applies to a run (design DD-1, DD-6, DD-9).

No receipt is stored or read: write answers the zero ref, latest None,
and applicable (False, ["not_run"]), the answers for a role never probed,
so no profile is taken as verified."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ReceiptCorrupt(Exception):
    """The latest receipt cannot be trusted: its object is missing or does
    not match `ref`, or a newer index file cannot be read (DD-1)."""

    def __init__(self, ref: str) -> None:
        super().__init__(ref)
        self.ref = ref


@dataclass(frozen=True)
class Versions:
    """The transport's and the agent CLI's versions; None when unknown."""

    transport: str | None
    agent_cli: str | None


def write(repo: str, role: str, receipt: dict[str, Any]) -> str:
    return "sha256:" + "0" * 64


def latest(repo: str, role: str) -> dict[str, Any] | None:
    return None


def applicable(
    repo: str, role: str, approved_digest: str, current: Versions
) -> tuple[bool, list[str]]:
    return False, ["not_run"]
