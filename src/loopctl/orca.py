"""Orca, the transport: its fixed argv and the parsing of its JSON (design
DD-1, DD-4). No function takes a command from its caller (ORC-01).

Only the environment is queried: the terminal and worker functions answer
Problem("transport_missing"), the answer for an Orca that cannot be used,
on which no probe goes on."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from loopctl import tools


@dataclass(frozen=True)
class Problem:
    """Why an Orca call gave no usable answer: `transport_missing`,
    `timeout`, `unparseable:<command>`, `exit:<n>`, and for worker_start
    `failed_stage:<stage>`. A value, never raised."""

    reason: str


@dataclass(frozen=True)
class Started:
    """The Task and the Dispatch of a worker Orca accepted."""

    task: str
    dispatch: str


MISSING = Problem("transport_missing")

# How long one call of Orca may take; `--version` and the queries answer in
# well under a second (research §5.4).
TIMEOUT_S = 10.0


def _call(argv: list[str]) -> tools.Completed | Problem:
    """`orca <argv>` when it ran and exited 0; else why not."""
    done = tools.run(["orca", *argv], TIMEOUT_S)
    reason = tools.failure(done)
    if reason == "missing":
        return MISSING
    return done if reason is None else Problem(reason)


def _query(command: list[str], *options: str) -> dict[str, Any] | Problem:
    """The `result` of `orca <command> <options> --json`; Orca's answer must
    be a JSON object with `ok: true`, else it is `unparseable:orca
    <command>`."""
    done = _call([*command, *options, "--json"])
    if isinstance(done, Problem):
        return done
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        answer = None
    if (
        not isinstance(answer, dict)
        or answer.get("ok") is not True
        or not isinstance(answer.get("result"), dict)
    ):
        return _unparseable(command)
    result: dict[str, Any] = answer["result"]
    return result


def _unparseable(command: list[str]) -> Problem:
    return Problem("unparseable:orca " + " ".join(command))


def version() -> str | Problem:
    """The version `orca --version` prints, as `1.4.218` (DD-9)."""
    done = _call(["--version"])
    if isinstance(done, Problem):
        return done
    found = tools.version(done.stdout)
    return _unparseable(["--version"]) if found is None else found


def status() -> dict[str, Any] | Problem:
    """The result of `orca status --json`: the app, its runtime, the graph."""
    return _query(["status"])


def _run_id(result: dict[str, Any] | Problem, command: list[str]) -> str | Problem:
    if isinstance(result, Problem):
        return result
    run = result.get("run")
    run_id = run.get("id") if isinstance(run, dict) else None
    if isinstance(run_id, str) and run_id:
        return run_id
    return _unparseable(command)


def run_current() -> str | None | Problem:
    """The id of the Run bound to the caller's Orca terminal; None when Orca
    answers `run: null`. An answer without `run` says nothing about the
    binding, so it is unparseable, never a reason to create a Run."""
    command = ["orchestration", "run-current"]
    result = _query(command)
    if not isinstance(result, Problem) and "run" in result and result["run"] is None:
        return None
    return _run_id(result, command)


def run_create(objective: str) -> str | Problem:
    """Create a Run, bound to the caller's Orca terminal; its id."""
    command = ["orchestration", "run-create"]
    return _run_id(_query(command, "--objective", objective), command)


def _listed(
    command: list[str], key: str, valid: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]] | Problem:
    """The objects Orca lists under `key` in the result of `command`, each
    `valid`; one that is not makes the whole answer unparseable."""
    result = _query(command)
    if isinstance(result, Problem):
        return result
    items = result.get(key)
    if isinstance(items, list) and all(
        isinstance(item, dict) and valid(item) for item in items
    ):
        return items
    return _unparseable(command)


def _strings(value: dict[str, Any], *names: str) -> bool:
    return all(isinstance(value.get(name), str) for name in names)


def _repo(repo: dict[str, Any]) -> bool:
    """Whether the fields preflight reads of a repo are strings: its id, its
    kind and the canonical key of its remote identity. A folder repo has
    no remote identity (samples/orca/repo-list.json), and a repo without
    one matches no remote."""
    identity = repo.get("gitRemoteIdentity")
    return _strings(repo, "id", "kind") and (
        identity is None
        or (isinstance(identity, dict) and _strings(identity, "canonicalKey"))
    )


def _worktree(worktree: dict[str, Any]) -> bool:
    """Whether the fields preflight reads of a workspace are strings: its
    id, its repo's id, its path, its displayName and its branch."""
    return _strings(worktree, "id", "repoId", "path", "displayName", "branch")


def repos() -> list[dict[str, Any]] | Problem:
    """The repos Orca has registered, with their kind and remote identity."""
    return _listed(["repo", "list"], "repos", _repo)


def worktrees() -> list[dict[str, Any]] | Problem:
    """The workspaces of every repo Orca has registered."""
    return _listed(["worktree", "list"], "worktrees", _worktree)


def terminal_create(worktree_id: str, title: str, command: str) -> str | Problem:
    return MISSING


def worker_start(
    spec: str, terminal: str, worktree_id: str, run: str
) -> Started | Problem:
    return MISSING


def worker_show(dispatch: str) -> dict[str, Any] | Problem:
    return MISSING


def terminal_wait(handle: str, timeout_ms: int) -> Literal["idle", "timeout"] | Problem:
    return MISSING


def terminal_close(handle: str) -> bool | Problem:
    return MISSING


def task_list(run: str) -> list[dict[str, Any]] | Problem:
    return MISSING
