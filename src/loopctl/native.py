"""The native records of the agent CLIs, the Claude transcript and the
Codex rollout: finding the one with the probe's marker, reading it back,
and judging the negatives (design DD-1, DD-6).

No record is searched or read: find_claude and find_codex answer
native_not_found, read_claude and read_codex an empty Session, and
judge_negative not_attempted. Those are the answers for missing evidence,
on which no item passes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Item:
    """One judged item of a receipt: whether it passed and why not, what
    was required and what was seen (None when it could not be seen), and
    the ids of the excerpts it rests on (DD-6)."""

    passed: bool
    reason: str | None
    required: object
    actual: object
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Found:
    """The one native record with the marker, or why there is none:
    `native_not_found`, `native_ambiguous` or `native_name_mismatch`."""

    path: Path | None
    problem: str | None


@dataclass(frozen=True)
class CallResult:
    """What a tool call returned; `denial` is the runtime's own refusal
    mark (Claude's toolDenialKind, Codex's sandbox marks)."""

    is_error: bool
    denial: str | None
    exit_code: int | None
    text: str


@dataclass(frozen=True)
class Call:
    """A tool call of the worker, the probe step it matches (None for
    none) and its result, if any."""

    id: str
    step: int | None
    command: str
    result: CallResult | None


@dataclass(frozen=True)
class Session:
    """A native record as read back: the prompt with the marker, the record
    the readback comes from (None when there is none), whether the turn is
    complete, the tool calls and the records."""

    prompt: dict[str, Any] | None
    context: dict[str, Any] | None
    complete: bool
    calls: list[Call]
    records: list[dict[str, Any]]


NOT_FOUND = Found(None, "native_not_found")


def find_claude(home: Path, marker: str, uuid: str, since: float) -> Found:
    return NOT_FOUND


def find_codex(codex_home: Path, marker: str, days: list[date]) -> Found:
    return NOT_FOUND


def read_claude(path: Path, marker: str) -> Session:
    return Session(None, None, False, [], [])


def read_codex(path: Path, marker: str) -> Session:
    return Session(None, None, False, [], [])


def judge_negative(
    call: Call | None, runtime: str, resources_unchanged: bool | None
) -> Item:
    return Item(False, "not_attempted", None, None)
