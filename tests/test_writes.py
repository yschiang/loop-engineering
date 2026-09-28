"""M-WRITE w1–w11: `write <op> --id`, readback, `result import`, writer end (design §4, §6, §8).

Everything goes through the public CLI (`loopctl.cli.main`) with a fake `herdr` (and
`opencode` for w9) on PATH, real git for the worktree, and `loopctl.clock.now` monkeypatched.
w1 runs two real processes. The Harness below is reused by test_observe.py and
test_public_path.py (imported by name; its test functions are not re-collected there).
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from loopctl import clock, store
from loopctl.cli import main

ROOT = Path(__file__).resolve().parents[1]
FEATURE = "F-1"
T0 = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
CLI = "import sys; from loopctl.cli import main; sys.exit(main(sys.argv[1:]))"
PANE, WORKSPACE = "w2:p1", "w2"
BRANCH = "feat/ingest"
PLAN = "docs/superpowers/plans/P03-ingest.md"
SPEC = "openspec/specs/ingest/spec.md"
TASK_ACS = {
    "T1": [{"id": "AC-1", "verify": "uv run pytest tests/test_ingest.py::test_parse"}],
    "T2": [
        {"id": "AC-2", "verify": "uv run pytest tests/test_ingest.py::test_retry"},
        {"id": "AC-3", "verify": "manual: docs/ingest.md lists the retry limit"},
    ],
}
TASK_SCOPE = {
    "T1": ["src/ingest.py", "tests/test_ingest.py"],
    "T2": ["src/ingest.py", "tests/test_ingest.py", "docs/ingest.md"],
}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def commit_all(cwd: Path, message: str) -> str:
    git(cwd, "add", "-A")
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", message)
    return git(cwd, "rev-parse", "HEAD")


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **delta: float) -> None:
        self.t += timedelta(**delta)


def marker(op_id: str) -> str:
    return f"loopctl-op:{FEATURE}/{op_id}"


def agent(attempt: str) -> str:
    return f"lc-{FEATURE}-{attempt}"


def plan_text(repo: Path, wt: Path) -> str:
    tasks = [{"id": t, "acs": TASK_ACS[t], "scope": TASK_SCOPE[t]} for t in ("T1", "T2")]
    block = yaml.safe_dump(
        {
            "workspace": {"source": str(repo), "worktree": str(wt), "branch": BRANCH, "base": "main"},
            "tasks": tasks,
        },
        sort_keys=False,
    )
    return (
        "# P03 ingest plan\n\n- T1: parse records (AC-1)\n- T2: retry (AC-2, AC-3)\n\n"
        f"```loopctl-plan\n{block}```\n"
    )


class Harness:
    """One feature, approved plan, a real repo; scenario calls accumulate in order."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, fakes) -> None:
        self.tmp, self.capsys, self.fakes, self.monkeypatch = tmp_path, capsys, fakes, monkeypatch
        self.home = tmp_path / "loopctl-home"
        self.user_home = tmp_path / "user-home"
        monkeypatch.setenv("LOOPCTL_HOME", str(self.home))
        monkeypatch.setenv("HOME", str(self.user_home))
        self.clock = Clock()
        monkeypatch.setattr(clock, "now", self.clock)
        self.repo, self.wt = tmp_path / "repo", tmp_path / "wt"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        shutil.copytree(ROOT / "profiles", self.repo / "profiles")
        files = {
            "workflow.yaml": (ROOT / "workflow.yaml").read_text(),
            PLAN: plan_text(self.repo, self.wt),
            SPEC: "# Ingest spec\n\n#### Scenario: AC-1\n#### Scenario: AC-2\n",
            "src/ingest.py": "def parse(line):\n    return line\n",
            "tests/test_ingest.py": "def test_placeholder():\n    pass\n",
            "evidence/client.log": "connect: ECONNREFUSED before the request was sent\n",
        }
        for rel, text in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        self.base_head = commit_all(self.repo, "init")
        monkeypatch.chdir(self.repo)
        self.calls: list[dict[str, Any]] = []
        self.token = ""

    # --- policy -------------------------------------------------------------------------

    def policy(self, change) -> None:
        path = self.repo / "workflow.yaml"
        data = yaml.safe_load(path.read_text())
        change(data)
        path.write_text(yaml.safe_dump(data))

    def limits(self, **values: float) -> None:
        self.policy(lambda p: p["limits"].update(values))

    # --- CLI ----------------------------------------------------------------------------

    def cli(self, *argv: str) -> tuple[int, dict]:
        code = main(list(argv))
        return code, json.loads(self.capsys.readouterr().out)

    def start(self) -> str:
        code, out = self.cli(
            "init", "--repo", "yschiang/loop-engineering", "--repo-id", "R_1",
            "--feature", FEATURE, "--issue", "7",
        )
        assert code == 0, out
        code, out = self.cli("claim", "--feature", FEATURE, "--actor", "orchestrate")
        assert code == 0, out
        self.token = out["result"]["token"]
        tok = f"--token={self.token}"
        for argv in (
            ["register", "binding", "--role", "spec", "--locator", SPEC, "--version", "spec-1"],
            ["register", "plan", "--locator", PLAN, "--version", "v1", "--producer", "implementer",
             "--calibrated-from", SPEC],
            ["decide", "approve_plan", "--id=approve-1", "--actor=human:alice", f"--target={PLAN}",
             "--version=v1", "--reason=approved with the user"],
        ):
            code, out = self.cli(*argv, "--feature", FEATURE, tok)
            assert code == 0, out
        return self.token

    def write(self, kind: str, op_id: str) -> tuple[int, dict]:
        return self.cli("write", kind, "--feature", FEATURE, f"--token={self.token}", "--id", op_id)

    def observe(self, source: str, attempt: str = "T1-a1", *extra: str) -> tuple[int, dict]:
        return self.cli(
            "observe", source, "--feature", FEATURE, f"--token={self.token}", "--attempt", attempt,
            *extra,
        )

    def import_result(self, attempt: str = "T1-a1", *extra: str) -> tuple[int, dict]:
        return self.cli(
            "result", "import", "--feature", FEATURE, f"--token={self.token}", "--attempt", attempt,
            *extra,
        )

    def next(self) -> dict:
        _, out = self.cli("next", "--feature", FEATURE)
        return dict(out["next"])

    def safety(self) -> dict | None:
        _, out = self.cli("safety", "--feature", FEATURE)
        return out["safety"]

    def decide(self, kind: str, **fields: str | bool) -> tuple[int, dict]:
        argv = ["decide", kind, "--feature", FEATURE, f"--token={self.token}"]
        values = {"actor": "human:alice", "version": "v1", "reason": "checked by hand", **fields}
        for key, value in values.items():
            flag = "--" + key.replace("_", "-")
            argv.append(flag if value is True else f"{flag}={value}")
        return self.cli(*argv)

    def state(self) -> dict:
        return store.load(FEATURE)[1]

    def revision(self) -> int:
        return store.load(FEATURE)[0]

    # --- fake herdr ---------------------------------------------------------------------

    def expect(self, *calls: dict) -> None:
        self.calls += [copy.deepcopy(c) for c in calls]
        self.fakes.use({"calls": self.calls})

    def herdr(self, *prefix: str) -> list[list[str]]:
        return [
            c["argv"] for c in self.fakes.calls()
            if c["tool"] == "herdr" and c["argv"][: len(prefix)] == list(prefix)
        ]

    def unexpected(self) -> list[dict]:
        return [c for c in self.fakes.calls() if c.get("unexpected")]

    # --- the dispatch path --------------------------------------------------------------

    def dispatch(self, until: str = "prompt", attempt: str = "T1-a1") -> None:
        """Approved plan → worktree → agent_start → prompt for the first attempt (all succeed)."""
        if not self.token:
            self.start()
        steps = [("worktree_create", "worktree", c_worktree_create(self))]
        steps.append(("agent_start", f"{attempt}.agent_start", c_agent_start(self, attempt)))
        steps.append(("prompt", f"{attempt}.prompt", c_prompt(attempt)))
        for kind, op_id, call in steps:
            if kind == "worktree_create" and op_id in self.state()["writes"]:
                continue
            assert self.next() == {"action": "write", "op": kind, "id": op_id}
            self.expect(call)
            code, out = self.write(kind, op_id)
            assert code == 0, out
            assert out["result"]["op"]["status"] == "succeeded", out
            if kind == until:
                return

    def assignment(self, attempt: str = "T1-a1") -> dict:
        return dict(self.state()["assignments"][attempt])

    def handle(self, attempt: str = "T1-a1") -> dict:
        return dict(self.state()["attempts"][attempt]["handle"])

    # --- worker side (what the fake worker would leave behind) --------------------------

    def work(self, rel: str = "src/ingest.py", text: str = "def parse(line):\n    return line.strip()\n") -> str:
        (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.wt / rel).write_text(text)
        return commit_all(self.wt, f"work on {rel}")

    def envelope(self, attempt: str = "T1-a1", **over: Any) -> dict:
        a = self.assignment(attempt)
        handle = self.handle(attempt)
        env = {
            "schema_version": 1,
            "attempt_id": attempt,
            "role": "implementer",
            "producer": "worker",
            "native": {"runtime": handle["runtime"], "session_id": handle["native_session_id"]},
            "cwd": str(self.wt),
            "versions": {"head": git(self.wt, "rev-parse", "HEAD"), "base": a["base"], "digests": a["digests"]},
            "body_kind": "implementation",
            "body": {"task_id": a["task_id"], "status": "completed", "summary": "parse strips whitespace"},
        }
        for key, value in over.items():
            if isinstance(value, dict) and isinstance(env.get(key), dict):
                env[key] = {**env[key], **value}
            else:
                env[key] = value
        return env

    def put_result(self, env: dict, attempt: str = "T1-a1") -> Path:
        path = Path(self.assignment(attempt)["result_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(env, indent=2) + "\n")
        return path

    def transcript(self, entries: list[dict], attempt: str = "T1-a1") -> Path:
        sid = self.handle(attempt)["native_session_id"]
        path = self.user_home / ".claude" / "projects" / "-tmp-wt" / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in entries))
        return path


@pytest.fixture
def h(tmp_path, monkeypatch, capsys, fakes) -> Harness:
    return Harness(tmp_path, monkeypatch, capsys, fakes)


# --- fake herdr calls (argv shapes from docs/research/2026-09-27/herdr-setup) ---------------


def c_worktree_create(h: Harness, **over: Any) -> dict:
    call = {
        "id": "worktree_create",
        "match": ["worktree", "create", "--cwd", str(h.repo), "--branch", BRANCH, "--base", "main",
                  "--path", str(h.wt), "--label", f"loopctl-{FEATURE}", "--no-focus"],
        "stdout": {"id": "cli:worktree:create", "result": {
            "type": "worktree_created",
            "root_pane": {"pane_id": PANE, "workspace_id": WORKSPACE, "cwd": str(h.wt)},
            "worktree": {"branch": BRANCH, "path": str(h.wt), "open_workspace_id": WORKSPACE}}},
        "effects": [{"run": ["git", "-C", str(h.repo), "worktree", "add", "-q", "-b", BRANCH, str(h.wt), "main"]}],
    }
    return {**call, **over}


def c_worktree_list(h: Harness, present: bool) -> dict:
    listed = [{"branch": "main", "path": str(h.repo), "is_linked_worktree": False}]
    if present:
        listed.append({"branch": BRANCH, "path": str(h.wt), "is_linked_worktree": True,
                       "open_workspace_id": WORKSPACE})
    return {"id": "worktree_list", "match": ["worktree", "list", "--cwd", str(h.repo)],
            "stdout": {"id": "cli:worktree:list", "result": {"type": "worktree_list", "worktrees": listed}}}


def c_agent_start(h: Harness, attempt: str = "T1-a1", kind: str = "claude") -> dict:
    return {
        "id": "agent_start",
        "match": ["agent", "start", agent(attempt), "--kind", kind, "--pane", PANE, "--timeout", "*", "--", "**"],
        "stdout": {"id": "cli:agent:start", "result": {"agent": {
            "name": agent(attempt), "agent": kind, "agent_status": "idle", "interactive_ready": True,
            "pane_id": PANE, "cwd": str(h.wt)}}},
    }


def c_prompt(attempt: str = "T1-a1", **over: Any) -> dict:
    call = {"id": "prompt", "match": ["agent", "prompt", agent(attempt), "*"],
            "stdout": {"id": "cli:agent:prompt", "result": {"type": "ok"}}}
    return {**call, **over}


def c_wait_output(attempt: str = "T1-a1", line: str | None = None, pane: str = PANE) -> dict:
    """Prompt readback: the pane shows `line` (default: this op's marker)."""
    line = marker(f"{attempt}.prompt") if line is None else line
    return {
        "id": "prompt_readback",
        "match": ["pane", "wait-output", PANE, "--match", marker(f"{attempt}.prompt"), "--timeout", "*"],
        "stdout": {"id": "cli:pane:wait-output", "result": {
            "matched_line": line, "pane_id": pane,
            "read": {"pane_id": pane, "workspace_id": WORKSPACE, "text": f"> {line}\n"}}},
    }


def c_wait_output_absent(attempt: str = "T1-a1") -> dict:
    return {
        "id": "prompt_readback_absent",
        "match": ["pane", "wait-output", PANE, "--match", marker(f"{attempt}.prompt"), "--timeout", "*"],
        "stdout": {"error": {"code": "timeout", "message": "timed out waiting for output match"},
                   "id": "cli:pane:wait-output"},
        "exit": 1,
    }


def c_agent_get(attempt: str = "T1-a1", status: str = "working", **over: Any) -> dict:
    call = {"id": "agent_get", "match": ["agent", "get", agent(attempt)],
            "stdout": {"id": "cli:agent:get", "result": {"agent": {
                "name": agent(attempt), "agent_status": status, "pane_id": PANE, "interactive_ready": True}}}}
    return {**call, **over}


def c_send_keys(attempt: str = "T1-a1") -> dict:
    return {"id": "stop", "match": ["agent", "send-keys", agent(attempt), "ctrl+c", "ctrl+c"],
            "stdout": {"id": "cli:agent:send-keys", "result": {"type": "ok"}}}


def c_process_info(running: bool) -> dict:
    procs = [{"pid": 100, "name": "zsh", "argv": ["-zsh"]}]
    if running:
        procs.append({"pid": 200, "name": "claude", "argv": ["claude", "--model", "claude-opus-5-5"]})
    return {"id": "process_info", "match": ["pane", "process-info", "--pane", PANE],
            "stdout": {"id": "cli:pane:process_info", "result": {"process_info": {
                "pane_id": PANE, "shell_pid": 100, "foreground_processes": procs}}}}


CLIENT_EXITED = {"stdout": "", "stderr": "herdr: connection closed by server\n", "exit": 1}


# --- native transcript entries (Claude Code shape, T1.2 facts) ------------------------------


def user(text: str, sid: str, cwd: str) -> dict:
    return {"type": "user", "sessionId": sid, "cwd": cwd, "message": {"role": "user", "content": text}}


def assistant(content: list[dict], stop: str, sid: str, cwd: str, uuid: str) -> dict:
    return {"type": "assistant", "uuid": uuid, "sessionId": sid, "cwd": cwd, "effort": "high",
            "message": {"id": f"msg_{uuid}", "role": "assistant", "model": "claude-opus-5-5",
                        "stop_reason": stop, "content": content}}


def tool_use(uid: str) -> dict:
    return {"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": "uv run pytest"}}


def tool_result(uid: str, sid: str, cwd: str) -> dict:
    return {"type": "user", "sessionId": sid, "cwd": cwd, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "is_error": False, "content": "1 passed"}]}}


def finished_turn(h: Harness, final_text: str, attempt: str = "T1-a1") -> list[dict]:
    sid, cwd = h.handle(attempt)["native_session_id"], str(h.wt)
    return [
        user(f"loopctl assignment {marker(f'{attempt}.prompt')} …", sid, cwd),
        assistant([{"type": "text", "text": "running tests"}, tool_use("tu-1")], "tool_use", sid, cwd, "a1"),
        tool_result("tu-1", sid, cwd),
        assistant([{"type": "text", "text": final_text}], "end_turn", sid, cwd, "a2"),
    ]


# --- w1 -------------------------------------------------------------------------------------


def test_w1_two_processes_writing_the_same_prompt_op_call_herdr_once(h):
    h.dispatch(until="agent_start")
    h.expect(c_prompt(sleep=0.5))
    argv = ["write", "prompt", "--feature", FEATURE, f"--token={h.token}", "--id", "T1-a1.prompt"]
    procs = [
        subprocess.Popen([sys.executable, "-c", CLI, *argv], cwd=h.repo, env=dict(os.environ),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    outs = [p.communicate(timeout=60) for p in procs]
    codes = sorted(p.returncode for p in procs)

    assert len(h.herdr("agent", "prompt")) == 1, outs
    assert h.unexpected() == []
    assert codes[0] == 0 and codes[1] in (0, 1), outs
    op = h.state()["writes"]["T1-a1.prompt"]
    assert op["status"] == "succeeded"
    assert len(op["attempts"]) == 1


# --- a prepared or retryable op is sent only while it is still allowed (design §2, §4, §8) --


class Crash(Exception):
    """The writing process vanished after persisting the op, before calling Herdr."""


def prepared_prompt(h: Harness, monkeypatch) -> None:
    from loopctl import writes

    h.dispatch(until="agent_start")

    def crash(feature: str, op_id: str) -> dict:
        raise Crash(op_id)

    with monkeypatch.context() as m:
        m.setattr(writes, "_call", crash)
        with pytest.raises(Crash):
            h.write("prompt", "T1-a1.prompt")
    op = h.state()["writes"]["T1-a1.prompt"]
    assert (op["status"], op["attempts"]) == ("prepared", [])


def scope_change(h: Harness) -> None:
    code, out = h.decide("scope_change", id="scope-1", target="AC-1", reason="AC-1 must also cover retries")
    assert code == 0, out
    assert h.state()["phase"] == "awaiting_approval"


@pytest.mark.parametrize("status", ["prepared", "failed"])
def test_an_existing_op_is_not_sent_once_approval_is_revoked(h, monkeypatch, status):
    if status == "prepared":
        prepared_prompt(h, monkeypatch)
    else:
        h.dispatch(until="agent_start")
        not_ready = {"stdout": {"error": {"code": "agent_not_ready", "message": "agent is not ready for prompts"},
                                "id": "cli:agent:prompt"}, "exit": 1}
        h.expect(c_prompt(**not_ready))
        code, out = h.write("prompt", "T1-a1.prompt")
        assert code == 0 and out["result"]["op"]["status"] == "failed", out
    sent = len(h.herdr("agent", "prompt"))
    scope_change(h)
    h.expect(c_prompt())

    code, out = h.write("prompt", "T1-a1.prompt")
    assert (code, out["result"].get("error")) == (3, "approval_changed"), out
    assert len(h.herdr("agent", "prompt")) == sent  # 0 sends after the approval was revoked
    op = h.state()["writes"]["T1-a1.prompt"]
    assert op["status"] == status and len(op["attempts"]) == sent

    # stopping the started agent stays allowed (D47)
    h.calls = []
    h.fakes.log.unlink()
    h.expect(c_send_keys(), c_process_info(running=False))
    assert h.write("stop", "T1-a1.stop")[0] == 0
    code, out = h.write("stop", "T1-a1.stop")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
    assert h.unexpected() == []


def test_an_op_prepared_under_an_earlier_approval_goes_to_a_human(h, monkeypatch):
    prepared_prompt(h, monkeypatch)
    scope_change(h)
    plan = h.repo / PLAN
    plan.write_text(plan.read_text() + "\nT1 also covers retries.\n")
    tok = f"--token={h.token}"
    code, out = h.cli("register", "plan", "--locator", PLAN, "--version", "v2", "--producer", "implementer",
                      "--calibrated-from", SPEC, "--feature", FEATURE, tok)
    assert code == 0, out
    code, out = h.decide("approve_plan", id="approve-2", target=PLAN, version="v2")
    assert code == 0, out

    assert h.next() == {"action": "human", "blockers": ["approval_changed:T1-a1.prompt"], "decision_kinds": []}
    code, out = h.write("prompt", "T1-a1.prompt")
    assert (code, out["result"].get("error")) == (3, "approval_changed"), out
    assert out["result"]["prepared_under"] == "approve-1" and out["result"]["approval"] == "approve-2"
    assert h.herdr("agent", "prompt") == []


def test_an_existing_op_is_not_sent_once_routing_no_longer_offers_it(h, monkeypatch):
    prepared_prompt(h, monkeypatch)
    h.expect(c_send_keys(), c_process_info(running=False))
    h.write("stop", "T1-a1.stop")
    code, out = h.write("stop", "T1-a1.stop")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
    assert h.state()["attempts"]["T1-a1"]["end"] is not None
    assert h.next() != {"action": "write", "op": "prompt", "id": "T1-a1.prompt"}
    h.expect(c_prompt())

    code, out = h.write("prompt", "T1-a1.prompt")
    assert (code, out["result"].get("error")) == (1, "not_routable"), out
    assert h.herdr("agent", "prompt") == []
    assert h.state()["writes"]["T1-a1.prompt"]["status"] == "prepared"


def test_an_unknown_op_is_still_read_back_once_approval_is_revoked(h):
    h.dispatch(until="agent_start")
    h.expect(c_prompt(**CLIENT_EXITED))
    code, out = h.write("prompt", "T1-a1.prompt")
    assert out["result"]["op"]["status"] == "unknown", out
    scope_change(h)
    h.expect(c_wait_output())

    code, out = h.write("prompt", "T1-a1.prompt")
    assert code == 0 and out["result"]["performed"] == "readback", out
    assert h.state()["writes"]["T1-a1.prompt"]["status"] == "succeeded"
    assert len(h.herdr("agent", "prompt")) == 1
    assert h.unexpected() == []


# --- w2 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("readback", ["own_marker", "other_op_marker", "other_pane"])
def test_w2_lost_receipt_is_read_back_by_marker_and_identity_never_resent(h, readback):
    h.dispatch(until="agent_start")
    h.expect(c_prompt(**CLIENT_EXITED))
    code, out = h.write("prompt", "T1-a1.prompt")
    assert code == 0, out
    assert out["result"]["op"]["status"] == "unknown"
    action = {"action": "write", "op": "prompt", "id": "T1-a1.prompt"}
    assert h.safety() == action
    assert h.next() == action

    line = {
        "own_marker": marker("T1-a1.prompt"),
        "other_op_marker": marker("T1-a1.prompt-retry"),  # a different op whose id extends ours
        "other_pane": marker("T1-a1.prompt"),
    }[readback]
    h.expect(c_wait_output(line=line, pane="w9:p1" if readback == "other_pane" else PANE))
    code, out = h.write("prompt", "T1-a1.prompt")
    op = h.state()["writes"]["T1-a1.prompt"]
    assert out["result"]["performed"] == "readback"
    assert len(op["readbacks"]) == 1
    if readback == "own_marker":
        assert code == 0, out
        assert op["status"] == "succeeded" and op["resolved_by"] == "readback"
    else:
        assert (code, out["result"]["error"]) == (3, "write_unknown"), out
        assert op["status"] == "unknown"
        assert "write_unknown:T1-a1.prompt" in h.state()["blockers"]
        assert h.safety() is None
        assert h.next()["action"] == "human"
        assert "resolve_operation" in h.next()["decision_kinds"]
        code, out = h.write("prompt", "T1-a1.prompt")
        assert (code, out["result"]["error"]) == (3, "write_unknown")
    assert len(h.herdr("agent", "prompt")) == 1  # 0 resends
    assert h.unexpected() == []


# --- w3 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["worktree_takes_effect_later", "prompt_not_found", "client_exited"])
def test_w3_unproven_outcomes_are_unknown_and_blocked_with_zero_resends(h, case):
    if case == "worktree_takes_effect_later":
        h.start()
        op_id, kind = "worktree", "worktree_create"
        h.expect(c_worktree_create(h, stdout={"error": {"code": "timeout", "message": "request timed out"},
                                              "id": "cli:worktree:create"}, exit=1, effects=[]))
        readback = c_worktree_list(h, present=False)
        prefix = ("worktree", "create")
    else:
        h.dispatch(until="agent_start")
        op_id, kind = "T1-a1.prompt", "prompt"
        failure = (
            {"stdout": {"error": {"code": "agent_not_found", "message": "agent target not found"},
                        "id": "cli:agent:prompt"}, "exit": 1}
            if case == "prompt_not_found" else CLIENT_EXITED
        )
        h.expect(c_prompt(**failure))
        readback = c_wait_output_absent()
        prefix = ("agent", "prompt")

    code, out = h.write(kind, op_id)
    assert out["result"]["op"]["status"] == "unknown", out
    assert h.safety() == {"action": "write", "op": kind, "id": op_id}
    h.expect(readback)
    code, out = h.write(kind, op_id)
    assert (code, out["result"]["error"]) == (3, "write_unknown"), out
    state = h.state()
    assert state["writes"][op_id]["status"] == "unknown"
    assert f"write_unknown:{op_id}" in state["blockers"]
    nxt = h.next()
    assert nxt["action"] == "human" and "resolve_operation" in nxt["decision_kinds"]

    code, out = h.write(kind, op_id)  # asking again sends nothing
    assert (code, out["result"]["error"]) == (3, "write_unknown")
    assert len(h.herdr(*prefix)) == 1
    assert h.unexpected() == []


# --- w4 -------------------------------------------------------------------------------------


def test_w4_three_still_running_readbacks_exhaust_and_the_fourth_is_refused(h):
    h.dispatch()
    h.expect(c_send_keys())
    code, out = h.write("stop", "T1-a1.stop")
    assert code == 0, out
    assert out["result"]["op"]["status"] == "unknown"  # keys sent; stopping is not proven
    for n in range(1, 4):
        assert h.safety() == {"action": "write", "op": "stop", "id": "T1-a1.stop"}
        h.expect(c_process_info(running=True))
        code, out = h.write("stop", "T1-a1.stop")
        assert out["result"]["performed"] == "readback"
        assert len(h.state()["writes"]["T1-a1.stop"]["readbacks"]) == n
        if n < 3:
            assert code == 0, out
            wait = h.safety()
            assert wait is not None and wait["action"] == "wait" and wait["poll_after_s"] == 10
            h.clock.advance(seconds=10)
        else:
            assert (code, out["result"]["error"]) == (3, "readback_exhausted")

    assert "readback_exhausted:T1-a1.stop" in h.state()["blockers"]
    calls = len(h.fakes.calls())
    code, out = h.write("stop", "T1-a1.stop")
    assert (code, out["result"]["error"]) == (3, "readback_exhausted")
    assert len(h.fakes.calls()) == calls
    assert h.state()["writes"]["T1-a1.stop"]["status"] == "unknown"


# --- w5 -------------------------------------------------------------------------------------


def dispatched_ops(h: Harness) -> list[str]:
    return sorted(k for k in h.state()["writes"] if k.endswith(".agent_start"))


@pytest.mark.parametrize("evidence", ["idle_or_done_only", "result_and_native_turn", "stop_confirmed", "unknown"])
def test_w5_writer_end_needs_authoritative_evidence(h, evidence):
    h.dispatch()
    if evidence == "idle_or_done_only":
        for status in ("idle", "done"):
            h.expect(c_agent_get(status=status))
            code, out = h.observe("worker")
            assert code == 0 and out["result"]["fact"]["agent_status"] == status, out
            h.clock.advance(seconds=30)
        code, out = h.observe("native")  # no native turn recorded
        assert code == 0, out
        assert h.state()["attempts"]["T1-a1"]["end"] is None
        assert h.next()["action"] in ("wait", "observe")
        assert dispatched_ops(h) == ["T1-a1.agent_start"]
    elif evidence == "result_and_native_turn":
        h.work()
        env = h.envelope()
        h.put_result(env)
        assert h.next() == {"action": "import", "attempt": "T1-a1"}
        code, out = h.import_result()
        assert code == 0, out
        assert h.state()["attempts"]["T1-a1"]["end"] is None  # the native turn is not seen yet
        assert h.next()["action"] == "observe" and h.next()["source"] == "native"
        h.transcript(finished_turn(h, "Done. " + json.dumps(env)))
        code, out = h.observe("native")
        assert code == 0, out
        assert h.state()["attempts"]["T1-a1"]["end"]["evidence"] == "result_and_native_turn"
        # The writer has ended; its idle TUI still holds the pane, so it is stopped (and the
        # stop confirmed) before the next agent is started in that pane.
        assert h.next() == {"action": "write", "op": "stop", "id": "T1-a1.stop"}
        h.expect(c_send_keys(), c_process_info(running=False))
        assert h.write("stop", "T1-a1.stop")[0] == 0
        assert h.next() == {"action": "write", "op": "stop", "id": "T1-a1.stop"}  # its readback
        assert h.write("stop", "T1-a1.stop")[0] == 0
        assert h.state()["attempts"]["T1-a1"]["end"]["evidence"] == "result_and_native_turn"
        assert h.next() == {"action": "write", "op": "agent_start", "id": "T2-a1.agent_start"}
    elif evidence == "stop_confirmed":
        h.expect(c_send_keys(), c_process_info(running=False))
        assert h.write("stop", "T1-a1.stop")[0] == 0
        code, out = h.write("stop", "T1-a1.stop")
        assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
        assert h.state()["attempts"]["T1-a1"]["end"]["evidence"] == "stop_confirmed"
        # T1 has no result, so the same task gets a new attempt.
        assert h.next() == {"action": "write", "op": "agent_start", "id": "T1-a2.agent_start"}
    else:
        h.expect(c_send_keys(), *[c_process_info(running=True)] * 3)
        h.write("stop", "T1-a1.stop")
        for _ in range(3):
            h.write("stop", "T1-a1.stop")
            h.clock.advance(seconds=10)
        nxt = h.next()
        assert nxt["action"] == "human" and "readback_exhausted:T1-a1.stop" in nxt["blockers"]
        assert h.state()["attempts"]["T1-a1"]["end"] is None
        assert dispatched_ops(h) == ["T1-a1.agent_start"]
    assert h.unexpected() == []


# --- w6 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("mismatch", ["attempt_id", "role", "cwd", "head", "scope", "worker_argv", "producer"])
def test_w6_mismatching_results_are_rejected_kept_and_listed(h, mismatch):
    h.dispatch()
    if mismatch == "scope":
        h.work("docs/unrelated.md", "not in T1 scope\n")
    else:
        h.work()
    over: dict[str, Any] = {
        "attempt_id": {"attempt_id": "T1-a9"},
        "role": {"role": "reviewer"},
        "cwd": {"cwd": str(h.repo)},
        "head": {"versions": {"head": h.base_head}},
        "scope": {},
        "worker_argv": {"body": {"task_id": "T1", "status": "completed", "summary": "s",
                                 "argv": ["uv", "run", "pytest", "-k", "not slow"]}},
        "producer": {"producer": "tool"},
    }[mismatch]
    path = h.put_result(h.envelope(**over))
    rev = h.revision()

    code, out = h.import_result()
    assert (code, out["result"]["error"]) == (1, "result_rejected"), out
    expected = {"scope": "scope:docs/unrelated.md"}.get(mismatch, mismatch)
    assert expected in out["result"]["diffs"]
    attempt = h.state()["attempts"]["T1-a1"]
    assert attempt["result"] is None
    kept = attempt["rejected"][-1]
    assert store.get_object(kept["object"][store.OBJECT_KEY]) == path.read_bytes()
    assert expected in kept["diffs"]
    assert h.revision() == rev + 1  # only the rejection record


def test_w6_a_rejected_result_after_a_finished_turn_goes_to_a_human(h):
    h.dispatch()
    h.work()
    h.put_result(h.envelope(cwd=str(h.repo)))
    assert h.import_result()[0] == 1
    h.transcript(finished_turn(h, "done, see the result file"))
    h.observe("worker")
    h.observe("native")
    nxt = h.next()
    assert nxt["action"] == "human" and nxt["blockers"] == ["result_rejected:T1-a1"]
    assert dispatched_ops(h) == ["T1-a1.agent_start"]


def test_stop_stays_allowed_while_the_feature_is_blocked(h):
    unknown_prompt(h)
    h.expect(c_send_keys(), c_process_info(running=False))
    code, out = h.write("stop", "T1-a1.stop")
    assert code == 0 and out["result"]["op"]["status"] == "unknown", out
    code, out = h.write("stop", "T1-a1.stop")
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
    assert h.state()["attempts"]["T1-a1"]["end"]["evidence"] == "stop_confirmed"
    assert "write_unknown:T1-a1.prompt" in h.state()["blockers"]  # other blockers stay


# --- w7 -------------------------------------------------------------------------------------


def test_w7_resent_result_is_a_no_op_and_different_bytes_conflict(h):
    h.dispatch()
    h.work()
    path = h.put_result(h.envelope())
    first = path.read_bytes()
    code, out = h.import_result()
    assert code == 0 and out["result"]["duplicate"] is False, out
    rev = h.revision()

    code, out = h.import_result()
    assert code == 0 and out["result"]["duplicate"] is True, out
    assert h.revision() == rev

    path.write_text(json.dumps(h.envelope(body={"summary": "a different claim"}), indent=2) + "\n")
    code, out = h.import_result()
    assert (code, out["result"]["error"]) == (3, "result_conflict"), out
    attempt = h.state()["attempts"]["T1-a1"]
    assert store.get_object(attempt["result"]["object"][store.OBJECT_KEY]) == first
    assert store.get_object(attempt["conflicts"][-1]["object"][store.OBJECT_KEY]) == path.read_bytes()
    assert "result_conflict:T1-a1" in h.state()["blockers"]
    assert h.next()["action"] == "human"


# --- w8 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["result_after_marker", "unparseable", "other_attempt_marker", "tool_running"])
def test_w8_native_only_result_is_extracted_by_the_tool_and_imported_once(h, case):
    h.dispatch()
    h.work()
    env = h.envelope()
    sid, cwd = h.handle()["native_session_id"], str(h.wt)
    own = user(f"loopctl assignment {marker('T1-a1.prompt')}", sid, cwd)
    if case == "result_after_marker":
        entries = finished_turn(h, "All done.\n```json\n" + json.dumps(env) + "\n```\n")
    elif case == "unparseable":
        entries = finished_turn(h, "All done, the result is in the usual place.")
    elif case == "other_attempt_marker":
        entries = [
            own,
            assistant([tool_use("tu-1")], "tool_use", sid, cwd, "a1"),
            tool_result("tu-1", sid, cwd),
            user(f"loopctl assignment {marker('T1-a0.prompt')}", sid, cwd),
            assistant([{"type": "text", "text": json.dumps(env)}], "end_turn", sid, cwd, "a2"),
        ]
    else:
        entries = [
            own,
            assistant([{"type": "text", "text": json.dumps(env)}, tool_use("tu-9")], "tool_use", sid, cwd, "a1"),
        ]
    raw = h.transcript(entries).read_bytes()

    code, out = h.observe("native")
    assert code == 0, out
    attempt = h.state()["attempts"]["T1-a1"]
    if case == "result_after_marker":
        assert h.next() == {"action": "import", "attempt": "T1-a1"}
        code, out = h.import_result()
        assert code == 0 and out["result"]["duplicate"] is False, out
        result = h.state()["attempts"]["T1-a1"]["result"]
        assert result["producer"] == "tool"
        assert result["native"] == {"runtime": "claude-code", "session_id": sid, "message_id": "msg_a2"}
        assert result["raw_digest"] == store.digest(env_text(entries))
        assert h.state()["attempts"]["T1-a1"]["end"]["evidence"] == "result_and_native_turn"
        rev = h.revision()
        code, out = h.import_result()
        assert code == 0 and out["result"]["duplicate"] is True
        assert h.revision() == rev
    elif case == "unparseable":
        assert attempt["result"] is None
        assert "native_result_unparseable:T1-a1" in h.state()["blockers"]
        assert h.next()["action"] == "human"
    else:
        assert attempt["result"] is None and attempt["end"] is None
        fact = h.state()["observations"]["current"]["native:T1-a1"]["native"]["fact"]
        assert fact["turn_complete"] is False and fact["result"] is None
        assert h.next()["action"] in ("wait", "observe")
    assert raw  # the transcript itself is untouched evidence
    assert dispatched_ops(h) == ["T1-a1.agent_start"]


def env_text(entries: list[dict]) -> bytes:
    """The raw final assistant text the tool extracted from."""
    return entries[-1]["message"]["content"][0]["text"].encode()


# --- w9 -------------------------------------------------------------------------------------


def use_opencode(h: Harness) -> None:
    h.policy(lambda p: p["profiles"]["implementer"].update(
        runtime="opencode", provider="openai", model="gpt-6-astra", effort="xhigh",
        settings="profiles/reviewer.opencode.json"))
    h.fakes.install("opencode")


@pytest.mark.parametrize("native_id", ["match", "mismatch"])
@pytest.mark.parametrize("runtime", ["claude-code", "opencode"])
def test_w9_handles_round_trip_by_attempt_and_a_wrong_native_id_is_rejected(h, runtime, native_id):
    if runtime == "opencode":
        use_opencode(h)
        h.start()
        steps = [c_worktree_create(h), c_agent_start(h, kind="opencode"), c_prompt()]
    else:
        h.start()
        steps = [c_worktree_create(h), c_agent_start(h), c_prompt()]
    h.expect(*steps)
    for kind, op_id in [("worktree_create", "worktree"), ("agent_start", "T1-a1.agent_start"),
                        ("prompt", "T1-a1.prompt")]:
        assert h.write(kind, op_id)[0] == 0
    handle = h.handle()
    assert set(handle) == {"herdr_session", "pane", "agent_name", "native_session_id", "runtime"}
    assert (handle["pane"], handle["agent_name"], handle["runtime"]) == (PANE, agent("T1-a1"), runtime)
    start_argv = h.herdr("agent", "start")[0]
    if runtime == "claude-code":
        assert re.fullmatch(r"[0-9a-f-]{36}", handle["native_session_id"])
        assert start_argv[start_argv.index("--session-id") + 1] == handle["native_session_id"]
        real = handle["native_session_id"]
        other = "00000000-0000-4000-8000-000000000000"
    else:
        assert handle["native_session_id"] is None  # not invented before the runtime reports it
        assert "--session-id" not in start_argv
        real, other = "ses_4f2a9c", "ses_0000other"
        export = {"info": {"id": real, "directory": str(h.wt), "version": "1.18.32"}, "messages": [
            {"info": {"id": "msg_u1", "role": "user"}, "parts": [{"type": "text", "text": marker("T1-a1.prompt")}]},
            {"info": {"id": "msg_a1", "role": "assistant", "finish": "tool-calls", "modelID": "gpt-6-astra",
                      "providerID": "openai", "agent": "loopctl-implementer"},
             "parts": [{"type": "tool", "state": {"status": "running", "input": {}}}]}]}
        h.expect(
            {"id": "list", "tool": "opencode", "match": ["session", "list", "--format", "json"],
             "stdout": [{"id": "ses_old", "directory": str(h.repo), "updated": 9},
                        {"id": real, "directory": str(h.wt), "updated": 5}]},
            {"id": "export", "tool": "opencode", "match": ["export", real], "stdout": export},
        )
        code, out = h.observe("native")
        assert code == 0, out
        assert h.handle()["native_session_id"] == real
    h.work()
    env = h.envelope(native={"session_id": real if native_id == "match" else other})
    h.put_result(env)
    code, out = h.import_result()
    if native_id == "match":
        assert code == 0, out
        assert h.state()["attempts"]["T1-a1"]["result"]["native"]["session_id"] == real
    else:
        assert (code, out["result"]["error"]) == (1, "result_rejected"), out
        assert "native_session_id" in out["result"]["diffs"]
        assert h.handle()["native_session_id"] == (real if runtime == "opencode" else handle["native_session_id"])
    assert h.unexpected() == []


def test_w9_a_result_written_before_the_native_id_is_known_waits_for_it(h):
    use_opencode(h)
    h.start()
    h.expect(c_worktree_create(h), c_agent_start(h, kind="opencode"), c_prompt())
    for kind, op_id in [("worktree_create", "worktree"), ("agent_start", "T1-a1.agent_start"),
                        ("prompt", "T1-a1.prompt")]:
        assert h.write(kind, op_id)[0] == 0
    real = "ses_4f2a9c"
    h.work()
    h.put_result(h.envelope(native={"session_id": real}))  # before loopctl learned the id
    assert h.handle()["native_session_id"] is None

    code, out = h.import_result()
    assert (code, out["result"].get("error")) == (1, "native_session_unknown"), out
    assert h.state()["attempts"]["T1-a1"]["rejected"] == []  # not a rejection: nothing to compare yet
    assert h.next() == {"action": "observe", "source": "worker", "purpose": "worker",
                        "read_key": "worker:T1-a1", "attempt": "T1-a1"}

    export = {"info": {"id": real, "directory": str(h.wt), "version": "1.18.32"}, "messages": [
        {"info": {"id": "msg_u1", "role": "user"}, "parts": [{"type": "text", "text": marker("T1-a1.prompt")}]},
        {"info": {"id": "msg_a1", "role": "assistant", "finish": "tool-calls", "modelID": "gpt-6-astra",
                  "providerID": "openai", "agent": "loopctl-implementer"},
         "parts": [{"type": "tool", "state": {"status": "running", "input": {}}}]}]}
    h.expect(
        {"id": "list", "tool": "opencode", "match": ["session", "list", "--format", "json"],
         "stdout": [{"id": real, "directory": str(h.wt), "updated": 5}]},
        {"id": "export", "tool": "opencode", "match": ["export", real], "stdout": export},
    )
    code, out = h.observe("native")
    assert code == 0, out
    assert h.handle()["native_session_id"] == real

    assert h.next() == {"action": "import", "attempt": "T1-a1"}
    code, out = h.import_result()
    assert code == 0, out
    assert h.state()["attempts"]["T1-a1"]["result"]["native"]["session_id"] == real
    assert h.unexpected() == []


# --- w10 ------------------------------------------------------------------------------------


def unknown_prompt(h: Harness) -> None:
    """A prompt whose outcome is unknown and whose readback found nothing: Blocked."""
    h.dispatch(until="agent_start")
    h.expect(c_prompt(**CLIENT_EXITED), c_wait_output_absent())
    h.write("prompt", "T1-a1.prompt")
    code, out = h.write("prompt", "T1-a1.prompt")
    assert code == 3, out
    assert "write_unknown:T1-a1.prompt" in h.state()["blockers"]


@pytest.mark.parametrize("resolution", ["bind_matches", "bind_differs", "not_delivered_by_not_found", "not_delivered_by_client_log"])
def test_w10_resolve_operation_effects(h, resolution):
    unknown_prompt(h)
    calls = len(h.fakes.calls())
    if resolution == "not_delivered_by_not_found":
        seen = h.state()["writes"]["T1-a1.prompt"]["readbacks"][-1]["observation"][store.OBJECT_KEY]
        (h.repo / "evidence" / "not-found.json").write_bytes(store.get_object(seen))
        fields = {"not_delivered": True, "evidence": "evidence/not-found.json"}
    elif resolution == "not_delivered_by_client_log":
        fields = {"not_delivered": True, "evidence": "evidence/client.log"}
    else:
        fields = {"bind": PANE, "evidence": "evidence/client.log"}
    code, out = h.decide("resolve_operation", id="ro-1", target="T1-a1.prompt", **fields)
    assert code == 0, out
    assert len(h.fakes.calls()) == calls  # the decision itself: 0 external calls
    action = {"action": "write", "op": "prompt", "id": "T1-a1.prompt"}
    assert h.safety() == action and h.next() == action

    if resolution == "bind_matches":
        h.expect(c_wait_output())
    elif resolution == "bind_differs":
        h.expect(c_wait_output(pane="w9:p1"))
    code, out = h.write("prompt", "T1-a1.prompt")
    op = h.state()["writes"]["T1-a1.prompt"]
    assert op["resolutions"]["ro-1"]["status"] in ("applied", "rejected")
    if resolution == "bind_matches":
        assert code == 0, out
        assert (op["status"], op["resolved_by"]) == ("succeeded", "human")
        assert "write_unknown:T1-a1.prompt" not in h.state()["blockers"]
    elif resolution in ("bind_differs", "not_delivered_by_not_found"):
        assert (code, out["result"]["error"]) == (3, "resolution_rejected"), out
        assert op["status"] == "unknown" and op["resolutions"]["ro-1"]["status"] == "rejected"
        assert "write_unknown:T1-a1.prompt" in h.state()["blockers"]
        if resolution == "not_delivered_by_not_found":
            assert len(h.fakes.calls()) == calls  # nothing to read: a not-found is not evidence
    else:
        assert code == 0, out
        assert (op["status"], op["resolved_by"]) == ("failed", "human")
        not_ready = {"stdout": {"error": {"code": "agent_not_ready", "message": "agent is not ready for prompts"},
                                "id": "cli:agent:prompt"}, "exit": 1}
        assert h.next() == action
        h.expect(c_prompt(**not_ready))
        code, out = h.write("prompt", "T1-a1.prompt")  # retry 1: not delivered again
        assert code == 0, out
        assert h.state()["writes"]["T1-a1.prompt"]["status"] == "failed"
        assert h.next() == action
        h.expect(c_prompt(**not_ready))
        code, out = h.write("prompt", "T1-a1.prompt")  # retry 2: the last one allowed
        assert (code, out["result"]["error"]) == (3, "retry_exhausted"), out
        assert h.state()["writes"]["T1-a1.prompt"]["status"] == "failed"
        before = len(h.fakes.calls())
        code, out = h.write("prompt", "T1-a1.prompt")  # retry 3 is refused
        assert (code, out["result"]["error"]) == (3, "retry_exhausted"), out
        assert len(h.fakes.calls()) == before
        assert "retry_exhausted:T1-a1.prompt" in h.state()["blockers"]
        assert len(h.state()["writes"]["T1-a1.prompt"]["attempts"]) == 3
    assert len(h.herdr("agent", "prompt")) == (3 if resolution == "not_delivered_by_client_log" else 1)
    assert h.unexpected() == []


# --- w11 ------------------------------------------------------------------------------------


def test_w11_a_prompt_past_its_time_limit_is_killed_and_unknown_not_failed(h):
    h.dispatch(until="agent_start")
    h.limits(write_call_s=0.5)
    late = h.tmp / "prompt-finished"
    h.expect(c_prompt(sleep=2.0, effects=[{"write": str(late), "text": "delivered"}]))
    started = time.monotonic()
    code, out = h.write("prompt", "T1-a1.prompt")
    assert time.monotonic() - started < 2.0
    assert code == 0, out
    op = h.state()["writes"]["T1-a1.prompt"]
    assert op["status"] == "unknown"
    assert op["attempts"][-1]["outcome"] == "unknown" and op["attempts"][-1]["reason"] == "call_timeout"
    time.sleep(2.5)
    assert not late.exists()  # the call was terminated, not left running

    assert h.safety() == {"action": "write", "op": "prompt", "id": "T1-a1.prompt"}
    h.expect(c_wait_output())
    code, out = h.write("prompt", "T1-a1.prompt")
    assert out["result"]["performed"] == "readback"
    assert len(h.herdr("agent", "prompt")) == 1  # only read back, never resent
    assert h.unexpected() == []


# --- unsupported ops ------------------------------------------------------------------------


@pytest.mark.parametrize("op", ["merge", "close", "release", "deploy", "publish_pr"])
def test_ops_outside_the_first_slice_kinds_are_unsupported_with_zero_calls(h, op):
    h.start()
    rev = h.revision()
    code, out = h.write(op, "x-1")
    assert (code, out["result"]["error"]) == (2, "unsupported")
    assert h.revision() == rev
    assert h.fakes.calls() == []


def test_write_needs_the_owner_token(h):
    h.start()
    h.token = "0" * 64
    code, out = h.write("worktree_create", "worktree")
    assert (code, out["result"]["error"]) == (4, "not_owner")
    assert h.fakes.calls() == []
