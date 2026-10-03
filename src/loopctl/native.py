"""The native records of the agent CLIs, the Claude transcript and the
Codex rollout: finding the one with the probe's marker, reading it back,
and judging the negatives and the settings loaded (design DD-1, DD-6).

The Codex rollout is neither searched nor read: find_codex answers
native_not_found and read_codex an empty Session, the answers for missing
evidence, on which no item passes; judge_negative knows the denial of
Claude alone (DENIALS)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
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
    `native_not_found`, `native_ambiguous`, `native_name_mismatch` or
    `native_unreadable`."""

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
UNREADABLE = Found(None, "native_unreadable")


def find_claude(home: Path, marker: str, uuid: str, since: float) -> Found:
    """The transcript of the probe session (DD-6): exactly one session file
    of a Claude project under `home`, modified at `since` or later, holds
    `marker`, and it is named after the session `uuid`. Subagents keep
    theirs a level deeper, which is not searched.

    Exactly one cannot be told while a file in scope may hold the marker
    unseen: a directory that cannot be listed, or a session file whose
    time or bytes cannot be read, is native_unreadable. A file is out of
    scope only once its time is known to be before `since`."""
    holding = []
    try:
        for path in _claude_sessions(home / ".claude" / "projects"):
            if path.stat().st_mtime >= since and marker.encode() in path.read_bytes():
                holding.append(path)
    except OSError:
        return UNREADABLE
    if not holding:
        return NOT_FOUND
    if len(holding) > 1:
        return Found(None, "native_ambiguous")
    if holding[0].name != f"{uuid}.jsonl":
        return Found(None, "native_name_mismatch")
    return Found(holding[0], None)


def _claude_sessions(projects: Path) -> list[Path]:
    """The session files of every Claude project in `projects`, as
    `Path.glob('*/*.jsonl')` names them, names that start with a dot
    included, except that a directory which cannot be listed raises
    OSError where glob would pass over it. Without `projects` there are
    none."""
    try:
        folders = _listed(projects, lambda entry: entry.is_dir())
    except FileNotFoundError:
        return []
    return sorted(
        path
        for folder in folders
        for path in _listed(folder, lambda entry: entry.name.endswith(".jsonl"))
    )


def _listed(directory: Path, chosen: Callable[[os.DirEntry[str]], bool]) -> list[Path]:
    """The entries of `directory` that are `chosen`, whatever their names:
    DD-6 searches every project and session file, hidden ones too.
    Raises OSError."""
    with os.scandir(directory) as entries:
        return [Path(entry.path) for entry in entries if chosen(entry)]


def find_codex(codex_home: Path, marker: str, days: list[date]) -> Found:
    return NOT_FOUND


class Unreadable(Exception):
    """A native record whose bytes were read but whose lines cannot all be
    decoded: it cannot show what the agent did (DD-6)."""


def _records(path: Path) -> list[dict[str, Any]]:
    """The records of the JSON-lines file `path`: the JSON objects among its
    lines. The agent ends every line it writes; a last line without its
    end is one it is still writing, and is no record until it is ended.
    A line that is ended but cannot be decoded, as one nested deeper than
    the decoder follows, may be the record of any call or hook, so the
    file is Unreadable; a blank line holds nothing. Raises OSError when
    the file cannot be read."""
    lines = path.read_bytes().split(b"\n")
    # What follows the last end of line: empty when every line is ended.
    lines, unfinished = lines[:-1], lines[-1]
    records = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError) as error:
            raise Unreadable(f"{path}: {type(error).__name__}") from error
        if isinstance(record, dict):
            records.append(record)
    try:
        record = json.loads(unfinished)
    except (ValueError, RecursionError):
        return records
    return records + [record] if isinstance(record, dict) else records


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


def result_text(content: Any) -> str:
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
    answered (DD-6, DD-7). Raises OSError when `path` cannot be read, and
    Unreadable when its lines cannot be decoded."""
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
                    result_text(block.get("content")),
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


# The mark a runtime's own denial leaves on a call's result (DD-6): Claude
# Code denies a call by a permission rule as `permission-rule`; a call the
# user rejected or interrupted was not denied by the settings.
DENIALS = {"claude": "permission-rule"}


def judge_negative(
    call: Call | None, runtime: str, resources_unchanged: bool | None
) -> Item:
    """A negative of the probe (DD-6): it holds only when the worker
    attempted `call`, the runtime denied it, and the resource the call
    would change did not change (`resources_unchanged`, None for a call
    with no resource to watch). The reason is the first of the three that
    fails: not_attempted; executed for a call the runtime let run, or
    not_a_runtime_denial for one refused other than by the runtime's own
    rule (DENIALS), or with no result that names it; resource_changed.

    Only Claude's denial is known here: a call of another runtime is
    never taken as denied."""
    denial = DENIALS.get(runtime)
    required: dict[str, object] = {"attempted": True, "runtime_denial": denial}
    if resources_unchanged is not None:
        required["resource_unchanged"] = True
    if call is None:
        return Item(False, "not_attempted", required, {"attempted": False})
    result = call.result
    actual = {
        "attempted": True,
        "command": call.command,
        "is_error": None if result is None else result.is_error,
        "denial": None if result is None else result.denial,
        "exit_code": None if result is None else result.exit_code,
        "resource_unchanged": resources_unchanged,
    }
    if result is not None and result.denial is None:
        return Item(False, "executed", required, actual)
    if (
        result is None
        or denial is None
        or not result.is_error
        or result.denial != denial
    ):
        return Item(False, "not_a_runtime_denial", required, actual)
    if resources_unchanged is False:
        return Item(False, "resource_changed", required, actual)
    return Item(True, None, required, actual)


def attachments(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """The Claude records that hold an attachment whose type starts with
    `kind`, in order."""
    return [
        record
        for record in records
        if isinstance(record.get("attachment"), dict)
        and str(record["attachment"].get("type", "")).startswith(kind)
    ]


def hooks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The records of every hook Claude ran: each attachment of a `hook_`
    type, whatever it names."""
    return attachments(records, "hook_")


# How much of a hook's command is kept as evidence (DD-6).
HOOK_CHARS = 200

# The record of the context a hook gave back to Claude. It names no
# command: the hook's own run is recorded beside it with its command, and
# its event (Claude sample, lines 6 and 7).
HOOK_CONTEXT = "hook_additional_context"


def hook_event(attachment: dict[str, Any]) -> str | None:
    """The event a hook record names: its hookEvent when that is text that
    is not empty, else None. Only such an event ties a context to a run."""
    event = attachment.get("hookEvent")
    return event if isinstance(event, str) and event else None


def without_command(ran: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The hook records in `ran` that cannot be judged by a command: a run
    whose command is missing or not text, and a context given back in an
    event (hook_event) of which no run names its command; a context that
    names no event is never vouched for. A hook that cannot be judged
    cannot count as one the profile keeps."""
    named = {
        hook_event(record["attachment"])
        for record in ran
        if record["attachment"].get("type") != HOOK_CONTEXT
        and isinstance(record["attachment"].get("command"), str)
    } - {None}
    unjudged = []
    for record in ran:
        attachment = record["attachment"]
        if attachment.get("type") == HOOK_CONTEXT:
            judged = hook_event(attachment) in named
        else:
            judged = isinstance(attachment.get("command"), str)
        if not judged:
            unjudged.append(record)
    return unjudged


def skill_names(records: list[dict[str, Any]]) -> list[str] | None:
    """The names of the skills Claude listed, from every skill listing in
    `records`; None without a listing, or with one whose names cannot be
    read."""
    listings = attachments(records, "skill_listing")
    names: list[str] = []
    for record in listings:
        listed = record["attachment"].get("names")
        if not isinstance(listed, list) or not all(
            isinstance(name, str) for name in listed
        ):
            return None
        names += listed
    return names if listings else None


def judge_claude_settings(
    records: list[dict[str, Any]], excluded: list[str], kept: list[str]
) -> Item:
    """settings.excluded for Claude (DD-6): no skill Claude listed belongs
    to an `excluded` plugin (its name starts with `<plugin>:`), and the
    command of every hook it ran holds one of `kept`. A hook that ran,
    however it ended, was loaded. Without a skill listing whose names can
    be read there is nothing to judge.

    An excluded skill or hook seen fails the item as excluded_loaded; else
    a hook record that cannot be judged by a command (without_command)
    fails it as hook_without_command. Such a record is shown by its type
    and the event it names (hook_event), not by its hookEvent as read,
    which can be any JSON value, even one nested deeper than the receipt's
    redaction can walk."""
    required = {"excluded_plugins": excluded, "hook_commands_hold_one_of": kept}
    names = skill_names(records)
    if names is None:
        return Item(False, "not_recorded", required, None)
    skills = [name for name in names if any(name.startswith(f"{p}:") for p in excluded)]
    commands = [record["attachment"].get("command") for record in hooks(records)]
    others = [
        command[:HOOK_CHARS]
        for command in commands
        if isinstance(command, str) and not any(k in command for k in kept)
    ]
    unjudged = [
        {
            "type": record["attachment"].get("type"),
            "hookEvent": hook_event(record["attachment"]),
        }
        for record in without_command(hooks(records))
    ]
    actual = {
        "skills_of_excluded_plugins": skills,
        "other_hooks": others,
        "hooks_without_command": unjudged,
    }
    if skills or others:
        return Item(False, "excluded_loaded", required, actual)
    if unjudged:
        return Item(False, "hook_without_command", required, actual)
    return Item(True, None, required, actual)
