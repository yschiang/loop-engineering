"""Preflight receipts per repo and role, outside the run state, and whether
the latest one applies to a run (design DD-1, DD-6, DD-9).

A receipt is an object of the store, so its ref is the digest of its
content. The index of each role lists the refs in the order they were
written; the latest one is the one that counts, whatever its verdict.

applicable answers (False, ["not_run"]) for every role, the answer for a
role never probed, so no profile is taken as verified."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopctl import clock, store


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


def role_dir(repo: str, role: str) -> Path:
    """Where the preflight of `role` in `repo` keeps its lock, its records
    and its receipt index (DD-8)."""
    return store.home() / "repos" / repo / "preflight" / role


def _index(repo: str, role: str) -> Path:
    return role_dir(repo, role) / "receipts"


def encode(receipt: dict[str, Any]) -> bytes:
    """The bytes a receipt is stored as, so its ref is their sha256."""
    text = json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode()


def write(repo: str, role: str, receipt: dict[str, Any]) -> str:
    """Store `receipt` and make it the latest of `role`; returns its ref."""
    ref = store.put_object(encode(receipt))
    record = {"receipt": ref, "verdict": receipt.get("verdict"), "at": clock.now()}
    store.append_record(_index(repo, role), record)
    return ref


def latest(repo: str, role: str) -> dict[str, Any] | None:
    """The receipt `role` last wrote, checked against its ref; None when it
    never wrote one.

    Raises ReceiptCorrupt, and never falls back to an older receipt, when
    the latest cannot be trusted: its object is missing or is not what its
    ref names, or an index file newer than the newest readable one cannot
    be read."""
    index = store.list_records(_index(repo, role))
    newest = index.items[-1] if index.items else None
    ref = None if newest is None else str(newest.get("receipt"))
    shown = 0 if newest is None else newest.get("seq")
    # append_record numbers every index record; one without is not its own.
    if type(shown) is not int:
        raise ReceiptCorrupt(str(ref))
    for name in index.skipped:
        if int(name.removesuffix(".json")) > shown:
            raise ReceiptCorrupt(name)
    if ref is None:
        return None
    try:
        value = json.loads(store.get_object(ref))
    except (store.ObjectError, ValueError):
        raise ReceiptCorrupt(ref) from None
    if not isinstance(value, dict):
        raise ReceiptCorrupt(ref)
    return value


def applicable(
    repo: str, role: str, approved_digest: str, current: Versions
) -> tuple[bool, list[str]]:
    return False, ["not_run"]
