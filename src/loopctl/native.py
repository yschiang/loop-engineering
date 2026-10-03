"""The native records of the agent CLIs, the Claude transcript and the
Codex rollout: finding the one with the probe's marker, reading it back,
and judging the negatives (design DD-1, DD-6).

The Codex rollout is neither searched nor read, and no negative is judged:
find_codex answers native_not_found, read_codex an empty Session, and
judge_negative not_attempted. Those are the answers for missing evidence,
on which no item passes."""

from __future__ import annotations

import json
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
    """The transcript of the probe session (DD-6): exactly one session file
    of a Claude project under `home`, modified at `since` or later, holds
    `marker`, and it is named after the session `uuid`. Subagents keep
    theirs a level deeper, which is not searched; a file that cannot be
    read is not one that holds the marker."""
    holding = []
    for path in sorted((home / ".claude" / "projects").glob("*/*.jsonl")):
        try:
            if path.stat().st_mtime >= since and marker.encode() in path.read_bytes():
                holding.append(path)
        except OSError:
            continue
    if not holding:
        return NOT_FOUND
    if len(holding) > 1:
        return Found(None, "native_ambiguous")
    if holding[0].name != f"{uuid}.jsonl":
        return Found(None, "native_name_mismatch")
    return Found(holding[0], None)


def find_codex(codex_home: Path, marker: str, days: list[date]) -> Found:
    return NOT_FOUND


def _records(path: Path) -> list[dict[str, Any]]:
    """The records of the JSON-lines file `path`. A line that is not a JSON
    object, such as the last one while the agent is still writing it, is
    no record. Raises OSError when the file cannot be read."""
    records = []
    for line in path.read_bytes().splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _content(record: dict[str, Any]) -> Any:
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _blocks(record: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The content blocks of `kind` in a record's message."""
    content = _content(record)
    if not isinstance(content, list):
        return []
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == kind
    ]


def _text(content: Any) -> str:
    """A tool result's content as text: a string, or its text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""


def read_claude(path: Path, marker: str) -> Session:
    """The probe session in the transcript `path`: the prompt is the first
    user record whose message is text holding `marker` (the session title
    and the last prompt hold it too, and are not the prompt); the readback
    is the first assistant record after it; the turn is complete when the
    last assistant record after it ended the turn with every tool call
    answered (DD-6, DD-7). Raises OSError when `path` cannot be read."""
    records = _records(path)
    start = next(
        (
            index
            for index, record in enumerate(records)
            if record.get("type") == "user"
            and isinstance(_content(record), str)
            and marker in _content(record)
        ),
        None,
    )
    if start is None:
        return Session(None, None, False, [], records)
    after = records[start + 1 :]
    answers = [record for record in after if record.get("type") == "assistant"]
    results: dict[str, CallResult] = {}
    for record in after:
        if record.get("type") != "user":
            continue
        denial = record.get("toolDenialKind")
        for block in _blocks(record, "tool_result"):
            if isinstance(block.get("tool_use_id"), str):
                results[block["tool_use_id"]] = CallResult(
                    block.get("is_error") is True,
                    denial if isinstance(denial, str) else None,
                    None,
                    _text(block.get("content")),
                )
    calls = []
    for record in answers:
        for block in _blocks(record, "tool_use"):
            given = block.get("input")
            given = given if isinstance(given, dict) else {}
            command = given.get("command", given.get("file_path"))
            call_id = block.get("id")
            if isinstance(call_id, str):
                calls.append(
                    Call(
                        call_id,
                        None,
                        command if isinstance(command, str) else "",
                        results.get(call_id),
                    )
                )
    last = answers[-1].get("message") if answers else None
    ended = isinstance(last, dict) and last.get("stop_reason") == "end_turn"
    complete = ended and all(call.result is not None for call in calls)
    return Session(
        records[start], answers[0] if answers else None, complete, calls, records
    )


def read_codex(path: Path, marker: str) -> Session:
    return Session(None, None, False, [], [])


def judge_negative(
    call: Call | None, runtime: str, resources_unchanged: bool | None
) -> Item:
    return Item(False, "not_attempted", None, None)
