"""Herdr 0.9.1 CLI calls used by preflight: launch, prompt, stop, process-info (T2.3 extends).

Argv and JSON shapes follow the H0 transcripts in docs/research/2026-09-27/herdr-setup/.
Every control call takes `session`: a Herdr session name selected with the global flag
(`herdr --session NAME <subcommand> …`), or None for the default session of the calling
environment. `version` needs no session.
"""

import json
from typing import Any

from loopctl.tools import ToolError, run


class HerdrError(Exception):
    def __init__(self, step: str, code: str) -> None:
        super().__init__(f"herdr {step}: {code}")
        self.step, self.code = step, code


def _call(step: str, args: list[str], timeout_s: float, session: str | None) -> dict[str, Any]:
    selector = ["--session", session] if session is not None else []
    try:
        out = run(["herdr", *selector, *args], timeout_s)
    except ToolError as e:
        try:
            code = json.loads(e.stdout)["error"]["code"]
        except (ValueError, KeyError, TypeError):
            code = f"exit_{e.code}"
        raise HerdrError(step, code) from e
    try:
        return json.loads(out).get("result", {}) if out.strip() else {}
    except ValueError as e:
        raise HerdrError(step, "unparseable_output") from e


def version(timeout_s: float) -> str:
    try:
        return run(["herdr", "--version"], timeout_s).strip()
    except ToolError as e:
        raise HerdrError("version", f"exit_{e.code}") from e


def open_worktree(
    source: str, path: str, label: str, timeout_s: float, *, session: str | None
) -> dict[str, Any]:
    """Open a workspace on an existing checkout; returns its root pane.

    `source` is the repo's main working tree: Herdr rejects a linked worktree as `--cwd`
    (`linked_worktree_source`). For the main checkout itself, source == path.
    """
    args = ["worktree", "open", "--cwd", source, "--path", path, "--label", label, "--no-focus"]
    return _call("worktree_open", args, timeout_s, session)["root_pane"]


def pane_run(pane: str, command: str, timeout_s: float, *, session: str | None) -> None:
    _call("pane_run", ["pane", "run", pane, command], timeout_s, session)


def start_agent(
    name: str, kind: str, pane: str, agent_args: list[str], timeout_s: float, *, session: str | None
) -> dict[str, Any]:
    ready_ms = str(int(timeout_s * 1000 / 2))
    args = ["agent", "start", name, "--kind", kind, "--pane", pane, "--timeout", ready_ms, "--"]
    return _call("agent_start", args + agent_args, timeout_s, session)["agent"]


def prompt(name: str, text: str, timeout_s: float, *, session: str | None) -> None:
    _call("agent_prompt", ["agent", "prompt", name, text], timeout_s, session)


def send_keys(name: str, keys: list[str], timeout_s: float, *, session: str | None) -> None:
    _call("agent_send_keys", ["agent", "send-keys", name, *keys], timeout_s, session)


def process_info(pane: str, timeout_s: float, *, session: str | None) -> dict[str, Any]:
    return _call(
        "pane_process_info", ["pane", "process-info", "--pane", pane], timeout_s, session
    )["process_info"]
