"""Orca, the transport: its fixed argv and the parsing of its JSON (design
DD-1, DD-4). No function takes a command from its caller (ORC-01): the
text a probe terminal runs and the probe task are built by preflight."""

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


def _ran(argv: list[str], timeout_s: float = TIMEOUT_S) -> tools.Completed | Problem:
    """`orca <argv>` when it ran to its end, whatever its exit; else why
    not."""
    done = tools.run(["orca", *argv], timeout_s)
    if done.status == "missing":
        return MISSING
    return done if done.status == "ok" else Problem(done.status)


def _call(argv: list[str]) -> tools.Completed | Problem:
    """`orca <argv>` when it ran and exited 0; else why not."""
    done = _ran(argv)
    if isinstance(done, Problem):
        return done
    reason = tools.failure(done)
    return done if reason is None else Problem(reason)


def _json(text: str) -> dict[str, Any] | None:
    """Orca's `--json` answer in `text`; None unless it is a JSON object."""
    try:
        answer = json.loads(text)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def _query(command: list[str], *options: str) -> dict[str, Any] | Problem:
    """The `result` of `orca <command> <options> --json`; Orca's answer must
    be a JSON object with `ok: true`, else it is `unparseable:orca
    <command>`."""
    done = _call([*command, *options, "--json"])
    if isinstance(done, Problem):
        return done
    answer = _json(done.stdout)
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
    command: list[str],
    key: str,
    valid: Callable[[dict[str, Any]], bool],
    *options: str,
) -> list[dict[str, Any]] | Problem:
    """The objects Orca lists under `key` in the result of `command`, each
    `valid`; one that is not makes the whole answer unparseable."""
    result = _query(command, *options)
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


def _field(value: Any, *path: str) -> Any:
    """A nested field of JSON `value`; None when a step is missing."""
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _string(value: Any, *path: str) -> str | None:
    """The non-empty string at `path` in JSON `value`; None otherwise."""
    value = _field(value, *path)
    return value if isinstance(value, str) and value else None


def terminal_create(worktree_id: str, title: str, command: str) -> str | Problem:
    """Open a terminal in the workspace `worktree_id` that runs the shell
    text `command`; its handle. Orca types the text into the login shell
    of the terminal (research §5.1)."""
    name = ["terminal", "create"]
    options = ["--worktree", f"id:{worktree_id}", "--title", title]
    result = _query(name, *options, "--command", command)
    if isinstance(result, Problem):
        return result
    handle = _string(result, "terminal", "handle")
    return _unparseable(name) if handle is None else handle


def worker_start(
    spec: str, terminal: str, worktree_id: str, run: str
) -> Started | Problem:
    """Dispatch the task `spec` to the agent already running in `terminal`,
    as a Task of `run`; the Task and the Dispatch Orca made.

    Orca exits 0 only for a worker that is ready; else it exits 1 with
    JSON that names the stage that failed (research §5.2), which is
    failed_stage:<stage>. No sample of that JSON exists, so the stage is
    looked for both in its `error` and in its `result`."""
    name = ["orchestration", "worker-start"]
    argv = [*name, "--spec", spec, "--terminal", terminal]
    argv += ["--worktree", f"id:{worktree_id}", "--run", run, "--json"]
    done = _ran(argv)
    if isinstance(done, Problem):
        return done
    answer = _json(done.stdout) or {}
    reason = tools.failure(done)
    if reason is not None:
        stage = _string(answer, "error", "failedStage") or _string(
            answer, "result", "failedStage"
        )
        return Problem(reason if stage is None else f"failed_stage:{stage}")
    result = answer.get("result") if answer.get("ok") is True else None
    task = _string(result, "taskId")
    dispatch = _string(result, "dispatchId")
    if task is None or dispatch is None:
        return _unparseable(name)
    return Started(task, dispatch)


def worker_show(dispatch: str) -> dict[str, Any] | Problem:
    """What Orca knows of the Dispatch `dispatch`: its status, its worker."""
    return _query(["orchestration", "worker-show"], "--dispatch", dispatch)


def terminal_wait(handle: str, timeout_ms: int) -> Literal["idle", "timeout"] | Problem:
    """Wait until the agent in the terminal `handle` is idle, at most
    `timeout_ms`. Orca answers `ok: true` when it is idle and the error
    `timeout` when the time ran out; any other answer, a terminal that has
    exited included, is a Problem (samples/orca/README)."""
    name = ["terminal", "wait"]
    argv = [*name, "--terminal", handle, "--for", "tui-idle"]
    argv += ["--timeout-ms", str(timeout_ms), "--json"]
    # Orca holds the call for up to timeout_ms before it answers.
    done = _ran(argv, timeout_ms / 1000 + TIMEOUT_S)
    if isinstance(done, Problem):
        return done
    answer = _json(done.stdout)
    if answer is not None and answer.get("ok") is True:
        return "idle"
    if answer is not None and _string(answer, "error", "code") == "timeout":
        return "timeout"
    reason = tools.failure(done)
    return _unparseable(name) if reason is None else Problem(reason)


def terminal_close(handle: str) -> bool | Problem:
    """Close the terminal `handle` and end what runs in it; whether Orca
    says it killed the terminal's process. That says nothing of the agent's
    own processes, which only process-info confirms (DD-7)."""
    name = ["terminal", "close"]
    result = _query(name, "--terminal", handle)
    if isinstance(result, Problem):
        return result
    killed = _field(result, "close", "ptyKilled")
    return killed if isinstance(killed, bool) else _unparseable(name)


def _task(task: dict[str, Any]) -> bool:
    """Whether the fields a probe reads of a Task are strings: its id and
    its spec."""
    return _strings(task, "id", "spec")


def task_list(run: str) -> list[dict[str, Any]] | Problem:
    """The Tasks of the Run `run`, with their specs."""
    return _listed(["orchestration", "task-list"], "tasks", _task, "--run", run)
