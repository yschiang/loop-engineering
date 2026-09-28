"""Herdr 0.9.1 CLI calls used by preflight: launch, prompt, stop, process-info; T2.3 adds the
write-op call, readback and bounded read functions below (T1.1 functions keep their meaning).

Argv and JSON shapes follow the H0 transcripts in docs/research/2026-09-27/herdr-setup/.
Every control call takes `session`: a Herdr session name selected with the global flag
(`herdr --session NAME <subcommand> …`), or None for the default session of the calling
environment. `version` needs no session.
"""

import json
import re
import subprocess
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


# --- T2.3: write ops and bounded reads. These only classify one call; whether to retry or
# read back is decided by loopctl.writes (design §4), never here.

# Herdr refused before acting (verified messages: "not ready for prompts", "start from the
# repo parent workspace"). Any other error, a timeout or a lost reply is not proof → unknown.
NOT_DELIVERED = frozenset({"agent_not_ready", "linked_worktree_source"})
MARKER = re.compile(r"loopctl-op:[A-Za-z0-9._/-]+")


class ReadFailed(Exception):
    """A transport failure of a read (time limit, lost client, unparseable reply)."""

    def __init__(self, reason: str, raw: str = "") -> None:
        super().__init__(reason)
        self.reason, self.raw = reason, raw


def argv(session: str | None, args: list[str]) -> list[str]:
    return ["herdr", *(["--session", session] if session is not None else []), *args]


def _error_code(text: str) -> str | None:
    try:
        return str(json.loads(text)["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


def _timed_out(e: ToolError) -> bool:
    return isinstance(e.__cause__, subprocess.TimeoutExpired)


def _facts(kind: str, result: dict[str, Any]) -> dict[str, Any]:
    if kind == "worktree_create":
        pane = result.get("root_pane") or {}
        return {"pane": pane.get("pane_id"), "workspace": pane.get("workspace_id")}
    if kind == "agent_start":
        agent = result.get("agent") or {}
        return {"pane": agent.get("pane_id"), "cwd": agent.get("cwd"), "agent_status": agent.get("agent_status")}
    return {}


def op_call(kind: str, full_argv: list[str], timeout_s: float) -> dict[str, Any]:
    """Run one op argv once: {outcome: succeeded|failed_not_delivered|unknown, reason, receipt, facts}."""
    try:
        out = run(full_argv, timeout_s)
    except ToolError as e:
        receipt = f"exit: {e.code}\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}"
        if _timed_out(e):
            return {"outcome": "unknown", "reason": "call_timeout", "receipt": receipt, "facts": {}}
        if e.code is None:  # the client never started: nothing was sent
            return {"outcome": "failed_not_delivered", "reason": "client_not_started", "receipt": receipt, "facts": {}}
        code = _error_code(e.stdout)
        if code in NOT_DELIVERED:
            return {"outcome": "failed_not_delivered", "reason": f"refused:{code}", "receipt": receipt, "facts": {}}
        reason = f"error:{code}" if code else "client_exited"
        return {"outcome": "unknown", "reason": reason, "receipt": receipt, "facts": {}}
    try:
        doc = json.loads(out) if out.strip() else {}
        facts = _facts(kind, doc.get("result") or {})
    except (ValueError, AttributeError, TypeError):
        return {"outcome": "unknown", "reason": "unparseable_output", "receipt": out, "facts": {}}
    if kind == "stop":  # keys delivered; only process-info proves the agent stopped
        return {"outcome": "unknown", "reason": "stop_unconfirmed", "receipt": out, "facts": {}}
    return {"outcome": "succeeded", "reason": None, "receipt": out, "facts": facts}


def read(full_argv: list[str], timeout_s: float) -> tuple[dict[str, Any], str]:
    """A bounded read: the parsed reply (a result, or Herdr's own error answer) and its text."""
    try:
        out = run(full_argv, timeout_s)
    except ToolError as e:
        if _timed_out(e):
            raise ReadFailed("read_timeout") from e
        if _error_code(e.stdout) is not None:
            return json.loads(e.stdout), e.stdout
        raise ReadFailed("client_error" if e.code is not None else "client_not_started", e.stderr) from e
    try:
        doc = json.loads(out)
    except ValueError:
        raise ReadFailed("unparseable_output", out) from None
    if not isinstance(doc, dict):
        raise ReadFailed("unparseable_output", out)
    return doc, out


def _readback_args(kind: str, expected: dict[str, Any]) -> list[str]:
    if kind == "worktree_create":
        return ["worktree", "list", "--cwd", expected["source"]]
    if kind == "agent_start":
        return ["agent", "get", expected["agent"]]
    if kind == "prompt":
        return ["pane", "wait-output", expected["pane"], "--match", expected["marker"], "--timeout", "1000"]
    return ["pane", "process-info", "--pane", expected["pane"]]


def _judge(kind: str, doc: dict[str, Any], expected: dict[str, Any]) -> tuple[str, str | None, dict[str, Any]]:
    """(confirmed|pending|absent|mismatch, detail, facts) for one readback reply."""
    if "error" in doc:
        return "absent", str((doc.get("error") or {}).get("code")), {}
    result = doc.get("result") or {}
    if kind == "worktree_create":
        found = [w for w in result.get("worktrees", []) if w.get("path") == expected["path"]]
        if not found:
            return "absent", "worktree_not_listed", {}
        if found[0].get("branch") != expected["branch"]:
            return "mismatch", "branch", {}
        return "confirmed", None, {"workspace": found[0].get("open_workspace_id")}
    if kind == "agent_start":
        agent = result.get("agent") or {}
        for field, key in (("pane_id", "pane"), ("cwd", "cwd")):
            if agent.get(field) != expected[key]:
                return "mismatch", key, {}
        if not agent.get("interactive_ready"):
            return "pending", "agent_not_ready", {}
        return "confirmed", None, _facts(kind, result)
    if kind == "prompt":
        read_ = result.get("read") or {}
        if expected["marker"] not in MARKER.findall(str(result.get("matched_line", ""))):
            return "mismatch", "other_marker", {}
        if {result.get("pane_id"), read_.get("pane_id")} != {expected["pane"]}:
            return "mismatch", "pane", {}
        if read_.get("workspace_id") != expected["workspace"]:
            return "mismatch", "workspace", {}
        return "confirmed", None, {}
    info = result.get("process_info") or {}
    procs = info.get("foreground_processes") or []
    if procs and all(p.get("pid") == info.get("shell_pid") for p in procs):
        return "confirmed", None, {}
    return "pending", "still_running", {}


def readback(kind: str, session: str | None, expected: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """One read-only check of an op's effect against its persisted expected identity."""
    raw = ""
    try:
        doc, raw = read(argv(session, _readback_args(kind, expected)), timeout_s)
        result, detail, facts = _judge(kind, doc, expected)
    except ReadFailed as e:
        return {"result": "transport_error", "detail": e.reason, "raw": e.raw, "facts": {}}
    except (AttributeError, TypeError, KeyError):  # a reply of an unexpected shape proves nothing
        return {"result": "transport_error", "detail": "unparseable_output", "raw": raw, "facts": {}}
    return {"result": result, "detail": detail, "raw": raw, "facts": facts}
