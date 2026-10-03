"""preflight's probe of the Claude profile: the launch in an Orca terminal,
the probe task, the wait, the readback from the transcript, the versions,
the stop and worker_done (design DD-4 steps 6-12a, DD-5, DD-6, DD-7)."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shlex
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from conftest import ApprovedRun, Clock, Fakes, OrcaEnv, ProbeRepo, Result, dig, git
from fakes import scenarios

from loopctl import orca, receipts, store

Cli = Callable[..., Result]

REPO = scenarios.REPO
FEATURE = "orca-preflight"

# preflight draws the probe worker's session uuid and its marker from
# uuid4; holding uuid4 to one value lets the fake name the transcript after
# the session, as Claude Code does (DD-6).
SESSION = uuid.UUID("84626209-eb35-425e-8baa-637b619925f4")
MARKER = "PFM-" + SESSION.hex[:12]


@pytest.fixture(autouse=True)
def ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uuid, "uuid4", lambda: SESSION)


@pytest.fixture
def probe(probe_repo: Callable[..., ProbeRepo]) -> ProbeRepo:
    return probe_repo()


def policy_text(timeout_s: int = 900) -> str:
    """The DD-2 example policy with its probe timeout set to `timeout_s`."""
    return scenarios.POLICY.replace("timeout_s: 900", f"timeout_s: {timeout_s}")


def probing(
    probe: ProbeRepo, orca_env: OrcaEnv, **options: Any
) -> dict[str, list[dict[str, Any]]]:
    """claude_probe for this test's workspaces and ids, Orca answering the
    Run's Tasks as the probe lists them (DD-6's resources)."""
    return scenarios.claude_probe(
        probe, orca_env.home, MARKER, str(SESSION), task_list=True, **options
    )


def preflight(cli: Cli, run: ApprovedRun) -> Result:
    return cli("preflight", *run.run, "--role", "implementer")


def latest() -> Any:
    return receipts.latest(REPO, "implementer")


PROBE_ITEMS = (
    "readback.model",
    "readback.effort",
    "placement.cwd",
    "placement.repo",
    "placement.branch",
    "permission.mode",
    "positive.inside_write",
    "task.accepted",
    "task.worker_done",
    "stop.confirmed",
    "version.consistent",
)


def test_probe_passes_launch_readback_and_stop_items(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env))

    r = preflight(cli, run)

    receipt = latest()
    passed = {name: dig(receipt, "items", name, "passed") for name in PROBE_ITEMS}
    assert passed == {name: True for name in PROBE_ITEMS}
    assert dig(receipt, "marker") == MARKER
    assert dig(receipt, "native_session_id") == str(SESSION)
    assert dig(receipt, "orca", "dispatch") == scenarios.PROBE_DISPATCH
    assert dig(receipt, "versions", "native") == "2.1.288"
    _, inside = scenarios.probe_files(probe.implementer, MARKER)
    assert inside.is_file()
    evidence = dig(receipt, "items", "positive.inside_write", "evidence") or []
    assert str(inside) in evidence
    assert r.get("result", "receipt") is not None


def calls_of(fakes: Fakes, *head: str) -> list[list[str]]:
    """The argv of every call of the fake orca that starts with `head`."""
    return [
        call["argv"]
        for call in fakes.calls()
        if call["tool"] == "orca" and call["argv"][: len(head)] == list(head)
    ]


def option(argv: list[str], name: str) -> str | None:
    """The value given to `name` in `argv`."""
    return argv[argv.index(name) + 1] if name in argv[:-1] else None


def hook_commands(settings: dict[str, Any]) -> list[str]:
    hooks = settings.get("hooks")
    return [
        hook.get("command", "")
        for groups in (hooks.values() if isinstance(hooks, dict) else [])
        for group in groups
        for hook in group.get("hooks", [])
    ]


def test_launch_command_and_settings_are_fixed(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env))

    preflight(cli, run)

    created = calls_of(fakes, "terminal", "create")
    assert len(created) == 1
    command = option(created[0], "--command") or ""
    directory = shlex.quote(str(Path(sys.executable).parent))
    words = shlex.split(command)
    settings_path = Path(option(words, "--settings") or "")
    expected = [
        f"PREFLIGHT_MARKER={MARKER}",
        f"PATH={directory}:$PATH",
        f"claude --model claude-opus-5-5 --effort high --session-id {SESSION}",
        "--setting-sources project,local",
        f"--settings {shlex.quote(str(settings_path))}",
        "--permission-mode dontAsk",
    ]
    at = [command.find(part) for part in expected]
    assert -1 not in at, (command, at)
    assert at == sorted(at)
    assert f"PATH={directory}:$PATH " in command
    assert settings_path.stat().st_mode & 0o777 == 0o600
    settings = json.loads(settings_path.read_text())
    commands = hook_commands(settings)
    assert len(commands) == len(scenarios.ORCA_HOOK_EVENTS)
    assert all("ORCA_AGENT_HOOK" in hook for hook in commands)
    plugins = {"superpowers@claude-plugins-official": True}
    assert settings.get("enabledPlugins") == plugins
    allow = dig(settings, "permissions", "allow") or []
    workspace = os.path.realpath(probe.implementer)
    assert f"Edit(/{workspace}/**)" in allow
    assert workspace.startswith("/") and f"Edit(//{workspace[1:]}/**)" in allow
    for sub in ("send", "check", "ask"):
        assert f"Bash(orca orchestration {sub} *)" in allow


def test_versions_are_normalised_from_real_outputs(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    # The fakes print `claude --version` and `orca --version` as the real
    # tools do: `2.1.288 (Claude Code)` and `1.4.218` (DD-10); the
    # transcript names `2.1.288`.
    fakes(probing(probe, orca_env, transcript={"version": "2.1.288"}))

    preflight(cli, run)

    receipt = latest()
    assert dig(receipt, "versions") == {
        "transport": "1.4.218",
        "agent_cli_before": "2.1.288",
        "agent_cli_after": "2.1.288",
        "native": "2.1.288",
    }
    assert dig(receipt, "items", "version.consistent", "passed") is True


def probes_dir(home: Path) -> Path:
    return home / "repos" / REPO / "preflight" / "implementer" / "probes"


def test_marker_is_recorded_before_the_terminal_exists(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    home: Path,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    probes = probes_dir(home)
    fakes(probing(probe, orca_env, snapshot=probes))

    preflight(cli, run)

    (created,) = [
        call
        for call in fakes.calls()
        if call["tool"] == "orca" and call["argv"][:2] == ["terminal", "create"]
    ]
    snapshot = dig(created, "snapshot", str(probes)) or {}
    at_create = [json.loads(text) for text in snapshot.values()]
    assert [(dig(r, "kind"), dig(r, "marker")) for r in at_create] == [
        ("started", MARKER)
    ]
    kinds = [record["kind"] for record in store.list_records(probes).items]
    assert kinds == ["started", "terminal", "dispatch", "closed"]


@dataclass
class Case:
    """What a row of test_readback_mismatch_fails_the_item probes with, and
    the fields it expects of some items."""

    options: dict[str, Any]
    expected: dict[str, dict[str, Any]]
    # Rows whose worker never ends its turn wait until the probe timeout.
    timeout: bool = False


Row = Callable[[ProbeRepo, OrcaEnv, Path], Case]

NATIVE_ITEMS = (
    "readback.model",
    "readback.effort",
    "placement.cwd",
    "placement.repo",
    "placement.branch",
    "permission.mode",
)


def failed(required: object, actual: object, reason: str | None) -> dict[str, Any]:
    return {"passed": False, "required": required, "actual": actual, "reason": reason}


def other_model(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    return Case(
        {"transcript": {"model": "claude-sonnet-5"}},
        {"readback.model": failed("claude-opus-5-5", "claude-sonnet-5", None)},
    )


def other_effort(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    return Case(
        {"transcript": {"effort": "medium"}},
        {"readback.effort": failed("high", "medium", None)},
    )


def other_directory(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    return Case(
        {"transcript": {"cwd": elsewhere}},
        {"placement.cwd": failed(str(probe.implementer), str(elsewhere), None)},
    )


def other_branch(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    git("-C", probe.implementer, "switch", "-q", "-c", "probe-other")
    return Case(
        {}, {"placement.branch": failed("preflight-engineer", "probe-other", None)}
    )


def other_repo(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    toplevel = git("-C", probe.author, "rev-parse", "--show-toplevel")
    return Case(
        {"transcript": {"cwd": probe.author}},
        {"placement.repo": failed(str(probe.implementer), toplevel, None)},
    )


def no_effort(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    return Case(
        {"transcript": {"omit": ("effort",)}},
        {"readback.effort": failed("high", None, "not_recorded")},
    )


def no_cwd(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    return Case(
        {"transcript": {"omit": ("cwd",)}},
        {"placement.cwd": failed(str(probe.implementer), None, "not_recorded")},
    )


STOPPED = {"stop.confirmed": {"passed": True}}


def prompt_only(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    return Case(
        {"transcript": {"turn": "prompt_only"}, "wait": "timeout"},
        {
            "readback.model": failed("claude-opus-5-5", None, "no_native_turn"),
            "readback.effort": failed("high", None, "no_native_turn"),
            **STOPPED,
        },
        timeout=True,
    )


def unfound(problem: str, files: str) -> Row:
    def row(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
        expected = {
            name: {"passed": False, "actual": None, "reason": problem}
            for name in NATIVE_ITEMS
        }
        return Case(
            {"files": files, "wait": "timeout"}, {**expected, **STOPPED}, timeout=True
        )

    return row


READ_BACK = {"readback.model": {"passed": True, "actual": "claude-opus-5-5"}}


def older_transcript(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    # A transcript of an earlier session that holds the marker as well.
    old = scenarios.claude_project(env.home, probe.reviewer) / "earlier.jsonl"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"type": "user", "message": {"content": MARKER}}) + "\n")
    hour_ago = time.time() - 3600
    os.utime(old, (hour_ago, hour_ago))
    return Case({}, READ_BACK)


def subagent_transcript(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    project = scenarios.claude_project(env.home, probe.implementer)
    agent = project / str(SESSION) / "subagents" / "agent-1.jsonl"
    agent.parent.mkdir(parents=True)
    prompt = {"type": "user", "message": {"content": MARKER}}
    agent.write_text(json.dumps(prompt) + "\n")
    return Case({}, READ_BACK)


def title_first(probe: ProbeRepo, env: OrcaEnv, tmp: Path) -> Case:
    place = str(probe.implementer)
    return Case(
        {"transcript": {"ai_title_first": True}},
        {"placement.cwd": {"passed": True, "required": place, "actual": place}},
    )


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(other_model, id="model"),
        pytest.param(other_effort, id="effort"),
        pytest.param(other_directory, id="cwd"),
        pytest.param(other_branch, id="branch"),
        pytest.param(other_repo, id="toplevel"),
        pytest.param(no_effort, id="no-effort-field"),
        pytest.param(no_cwd, id="no-cwd-field"),
        pytest.param(prompt_only, id="no-native-turn"),
        pytest.param(unfound("native_not_found", "none"), id="native-not-found"),
        pytest.param(unfound("native_ambiguous", "two"), id="native-ambiguous"),
        pytest.param(
            unfound("native_name_mismatch", "misnamed"), id="native-name-mismatch"
        ),
        pytest.param(older_transcript, id="older-transcript"),
        pytest.param(subagent_transcript, id="subagent-transcript"),
        pytest.param(title_first, id="title-before-prompt"),
    ],
)
def test_readback_mismatch_fails_the_item(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    tmp_path: Path,
    row: Row,
) -> None:
    case = row(probe, orca_env, tmp_path)
    run = approved_run(REPO, FEATURE, policy_text(60 if case.timeout else 900))
    fakes(probing(probe, orca_env, **case.options))

    preflight(cli, run)

    receipt = latest()
    for name, fields in case.expected.items():
        got = {field: dig(receipt, "items", name, field) for field in fields}
        assert (name, got) == (name, fields)


@pytest.mark.parametrize(
    ("versions", "native"),
    [
        pytest.param(("2.1.289", "2.1.289"), "2.1.288", id="not-the-cli-that-ran"),
        pytest.param(("2.1.288", "2.1.289"), "2.1.288", id="updated-during-probe"),
    ],
)
def test_version_must_match_the_running_agent(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    versions: tuple[str, str],
    native: str,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    options = {"versions": versions, "transcript": {"version": native}}
    fakes(probing(probe, orca_env, **options))

    preflight(cli, run)

    item = dig(latest(), "items", "version.consistent") or {}
    before, after = versions
    assert item.get("passed") is False
    assert item.get("reason") == "agent_version_mismatch"
    assert item.get("actual") == {"before": before, "after": after, "native": native}


def test_task_not_reported_fails_worker_done(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    # The transcript ends its turn, but Orca's Dispatch is still dispatched.
    fakes(probing(probe, orca_env, worker_done=False))

    preflight(cli, run)

    receipt = latest()
    assert dig(receipt, "items", "task.worker_done", "passed") is False
    assert dig(receipt, "items", "task.worker_done", "actual") == "dispatched"
    assert len(calls_of(fakes, "terminal", "close")) == 1
    assert dig(receipt, "items", "stop.confirmed", "passed") is True


def after_close(fakes: Fakes, sleeps: list[tuple[float, int]]) -> list[str]:
    """The sleeps and process listings after `terminal close`, in order;
    each sleep is logged with the number of fake calls made before it."""
    calls = fakes.calls()
    closed = next(
        index
        for index, call in enumerate(calls)
        if call["tool"] == "orca" and call["argv"][:2] == ["terminal", "close"]
    )
    events: list[str] = []
    for index, call in enumerate([*calls, None]):
        events += [f"sleep {s}" for s, at in sleeps if at == index and at > closed]
        if call is not None and index > closed and call["tool"] == "ps":
            events.append("ps " + " ".join(call["argv"]))
    return events


LISTED = "ps -Eww -ax -o command="
COMMANDS = "ps -ax -o command="


@pytest.mark.parametrize(
    ("running", "confirmed", "events", "last"),
    [
        pytest.param(
            10, False, ["sleep 0.5", LISTED] * 10, "stop_unconfirmed", id="never"
        ),
        pytest.param(
            2, True, ["sleep 0.5", LISTED] * 3 + [COMMANDS], "closed", id="third-check"
        ),
    ],
)
def test_stop_must_be_confirmed_by_process_info(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    running: int,
    confirmed: bool,
    events: list[str],
    last: str,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    # terminal close answers ptyKilled: true, yet the worker is still listed.
    fakes(probing(probe, orca_env, running_after_close=running))
    sleeps: list[tuple[float, int]] = []

    def sleep(seconds: float) -> None:
        sleeps.append((seconds, len(fakes.calls())))
        clock.sleep(seconds)

    monkeypatch.setattr("loopctl.clock.sleep", sleep)

    preflight(cli, run)

    assert dig(latest(), "items", "stop.confirmed", "passed") is confirmed
    assert after_close(fakes, sleeps) == events
    kinds = [record["kind"] for record in store.list_records(probes_dir(home)).items]
    assert kinds[-1] == last
    assert ("closed" in kinds) is confirmed


def test_probe_timeout_still_stops_the_worker(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(60))
    start = clock.at
    options = {"transcript": {"turn": "prompt_only"}, "wait": "timeout"}
    fakes(probing(probe, orca_env, **options))

    r = preflight(cli, run)

    assert (clock.at - start).total_seconds() >= 60
    assert "probe_timeout" in (r.get("blocked", "reasons") or [])
    assert len(calls_of(fakes, "terminal", "close")) == 1
    assert dig(latest(), "items", "stop.confirmed", "passed") is True


def test_wait_failure_stops_waiting_at_once(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(60))
    # The worker never ends its turn, and its terminal is gone: every
    # `terminal wait` fails with an error other than timeout.
    options = {"transcript": {"turn": "prompt_only"}, "wait": "failed"}
    fakes(probing(probe, orca_env, **options))

    r = preflight(cli, run)

    assert len(calls_of(fakes, "terminal", "wait")) == 1
    assert "wait_failed:exit:1" in (r.get("blocked", "reasons") or [])
    assert "probe_timeout" not in (r.get("blocked", "reasons") or [])
    receipt = latest()
    assert dig(receipt, "items", "readback.model", "reason") == "no_native_turn"
    assert len(calls_of(fakes, "terminal", "close")) == 1
    assert dig(receipt, "items", "stop.confirmed", "passed") is True


def test_worker_start_failure_reports_the_stage(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env, failed_stage="agent_readiness"))

    r = preflight(cli, run)

    assert "task_not_started:agent_readiness" in (r.get("blocked", "reasons") or [])
    assert len(calls_of(fakes, "terminal", "close")) == 1
    receipt = latest()
    assert dig(receipt, "items", "stop.confirmed", "passed") is True
    assert dig(receipt, "items", "task.worker_done", "reason") == "task_not_started"


@pytest.mark.parametrize(
    ("writable_on_close", "stop_fails", "kinds"),
    [
        pytest.param(True, False, ["started", "closed"], id="terminal-record"),
        pytest.param(False, False, ["started"], id="stop-record-too"),
        pytest.param(True, True, ["started"], id="stop-record-fails-otherwise"),
    ],
)
def test_terminal_record_failure_still_stops_the_worker(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    writable_on_close: bool,
    stop_fails: bool,
    kinds: list[str],
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    probes = probes_dir(home)
    fakes(probing(probe, orca_env, dispatched=False))
    # Once the terminal exists, the directory of the probe records is not
    # writable, so its record fails in the store (EACCES); in the second row
    # it stays so for the record of the stop.
    create, close = orca.terminal_create, orca.terminal_close

    def creating(worktree_id: str, title: str, command: str) -> str | orca.Problem:
        handle = create(worktree_id, title, command)
        probes.chmod(0o500)
        return handle

    def closing(handle: str) -> bool | orca.Problem:
        closed = close(handle)
        if writable_on_close:
            probes.chmod(0o700)
        return closed

    monkeypatch.setattr(orca, "terminal_create", creating)
    monkeypatch.setattr(orca, "terminal_close", closing)
    if stop_fails:
        # The record of the stop fails with an error of its own, which the
        # filesystem cannot tell apart from the first one (EACCES both).
        append = store.append_record

        def failing(directory: Path, payload: dict[str, Any]) -> int:
            if payload.get("kind") in ("closed", "stop_unconfirmed"):
                error = OSError(errno.EIO, os.strerror(errno.EIO))
                raise store.IOFailure("write_record", error, committed=False)
            return append(directory, payload)

        monkeypatch.setattr(store, "append_record", failing)

    try:
        r = preflight(cli, run)
    finally:
        probes.chmod(0o700)

    assert len(calls_of(fakes, "terminal", "close")) == 1
    tools = [call["tool"] for call in fakes.calls()]
    closed = next(
        index
        for index, call in enumerate(fakes.calls())
        if call["tool"] == "orca" and call["argv"][:2] == ["terminal", "close"]
    )
    assert "ps" in tools[closed + 1 :]
    assert r.exc is None
    assert r.code == 6
    assert r.get("result", "error") == "io_error"
    assert r.get("result", "op") == "write_record"
    assert r.get("result", "errno") == "EACCES"
    assert [record["kind"] for record in store.list_records(probes).items] == kinds


def unreadable_file(path: Path, text: str) -> Path:
    """Make `path` hold `text`, modified after the probe started (an hour
    ahead), and readable by no one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    ahead = time.time() + 3600
    os.utime(path, (ahead, ahead))
    path.chmod(0o000)
    return path


def unreadable_transcript(probe: ProbeRepo, env: OrcaEnv) -> tuple[str, Path, int]:
    # The probe's own transcript is there, under its name, but unreadable.
    project = scenarios.claude_project(env.home, probe.implementer)
    text = scenarios.claude_transcript(
        probe.implementer, MARKER, str(SESSION), scenarios.BOUND_RUN
    )
    return "none", unreadable_file(project / f"{SESSION}.jsonl", text), 0o600


def unreadable_other(probe: ProbeRepo, env: OrcaEnv) -> tuple[str, Path, int]:
    # The probe's transcript is readable and holds the marker; another
    # session file in scope cannot be read, so it may hold the marker too.
    project = scenarios.claude_project(env.home, probe.reviewer)
    return "one", unreadable_file(project / "other.jsonl", "{}\n"), 0o600


def unstatable_other(probe: ProbeRepo, env: OrcaEnv) -> tuple[str, Path, int]:
    # Another project lists its session file but lets no one stat it: its
    # modification time is unknown, so it is not known to be out of scope.
    project = scenarios.claude_project(env.home, probe.reviewer)
    session = project / "other.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text("{}\n")
    project.chmod(0o400)
    return "one", project, 0o700


def unlistable_project(probe: ProbeRepo, env: OrcaEnv) -> tuple[str, Path, int]:
    # Another project cannot be listed: its session files are unknown.
    project = scenarios.claude_project(env.home, probe.reviewer)
    (project / "other.jsonl").parent.mkdir(parents=True)
    (project / "other.jsonl").write_text("{}\n")
    project.chmod(0o000)
    return "one", project, 0o700


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(unreadable_transcript, id="transcript-unreadable"),
        pytest.param(unreadable_other, id="other-session-unreadable"),
        pytest.param(unstatable_other, id="other-session-unstatable"),
        pytest.param(unlistable_project, id="other-project-unlistable"),
    ],
)
def test_unreadable_native_file_fails_the_readback(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    row: Callable[[ProbeRepo, OrcaEnv], tuple[str, Path, int]],
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(60))
    files, locked, mode = row(probe, orca_env)
    # The search cannot tell how many transcripts hold the marker, so the
    # worker's turn is never seen to end and the probe times out.
    fakes(probing(probe, orca_env, files=files, wait="timeout"))

    try:
        r = preflight(cli, run)
    finally:
        locked.chmod(mode)

    receipt = latest()
    expected = {"passed": False, "actual": None, "reason": "native_unreadable"}
    for name in NATIVE_ITEMS:
        got = {field: dig(receipt, "items", name, field) for field in expected}
        assert (name, got) == (name, expected)
    assert len(calls_of(fakes, "terminal", "close")) == 1
    assert dig(receipt, "items", "stop.confirmed", "passed") is True
    assert r.get("result", "verdict") == "unverified"


def holding_marker(path: Path) -> Path:
    """Make `path` a session file that holds the marker, modified after the
    probe started (an hour ahead)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "user", "message": {"content": MARKER}}))
    ahead = time.time() + 3600
    os.utime(path, (ahead, ahead))
    return path


def hidden_project_copy(probe: ProbeRepo, env: OrcaEnv) -> tuple[Path | None, str]:
    # A project whose name starts with a dot holds a second transcript.
    projects = scenarios.claude_project(env.home, probe.implementer).parent
    holding_marker(projects / ".hidden" / "other.jsonl")
    return None, "native_ambiguous"


def hidden_project_unreadable(
    probe: ProbeRepo, env: OrcaEnv
) -> tuple[Path | None, str]:
    # A project whose name starts with a dot holds an unreadable session.
    projects = scenarios.claude_project(env.home, probe.implementer).parent
    locked = unreadable_file(projects / ".hidden" / "other.jsonl", "{}\n")
    return locked, "native_unreadable"


def hidden_session_copy(probe: ProbeRepo, env: OrcaEnv) -> tuple[Path | None, str]:
    # The probe's own project holds a second transcript named with a dot.
    project = scenarios.claude_project(env.home, probe.implementer)
    holding_marker(project / ".other.jsonl")
    return None, "native_ambiguous"


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(hidden_project_copy, id="hidden-project-ambiguous"),
        pytest.param(hidden_project_unreadable, id="hidden-project-unreadable"),
        pytest.param(hidden_session_copy, id="hidden-session-ambiguous"),
    ],
)
def test_hidden_projects_are_in_the_search_scope(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    row: Callable[[ProbeRepo, OrcaEnv], tuple[Path | None, str]],
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(60))
    locked, reason = row(probe, orca_env)
    # A name that starts with a dot is in scope (DD-6), so exactly one
    # transcript cannot be told and the probe times out.
    fakes(probing(probe, orca_env, wait="timeout"))

    try:
        preflight(cli, run)
    finally:
        if locked is not None:
            locked.chmod(0o600)

    receipt = latest()
    expected = {"passed": False, "actual": None, "reason": reason}
    for name in NATIVE_ITEMS:
        got = {field: dig(receipt, "items", name, field) for field in expected}
        assert (name, got) == (name, expected)


# A line nested deeper than the JSON decoder follows.
NESTED = "[" * 100_000 + "]" * 100_000


@pytest.mark.parametrize(
    ("tail", "timeout_s", "wait", "reason"),
    [
        pytest.param(NESTED + "\n", 60, "timeout", "native_unreadable", id="nested"),
        # A whole line that is not JSON may be the record of a hook or a
        # call; it cannot be passed over.
        pytest.param(
            '{"type": "attachment", "attachment": {"type": "hook_success"\n',
            60,
            "timeout",
            "native_unreadable",
            id="not-json",
        ),
        # The last line, without its end, is one the agent is still writing.
        pytest.param(
            '{"type": "assistant", "message": {"model": "claude-op',
            900,
            "idle",
            None,
            id="unfinished-last-line",
        ),
    ],
)
def test_undecodable_transcript_line_fails_the_readback(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    tail: str,
    timeout_s: int,
    wait: str,
    reason: str | None,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(timeout_s))
    fakes(probing(probe, orca_env, wait=wait, transcript={"tail": tail}))

    r = preflight(cli, run)

    receipt = latest()
    expected = {"passed": reason is None, "reason": reason}
    for name in NATIVE_ITEMS:
        got = {field: dig(receipt, "items", name, field) for field in expected}
        assert (name, got) == (name, expected), r.exc
    assert dig(receipt, "items", "stop.confirmed", "passed") is True
    assert r.exc is None
    verdict = "verified" if reason is None else "unverified"
    assert (r.code, r.get("result", "verdict")) == (0 if reason is None else 3, verdict)


# The negatives of the Claude probe, by probe step (DD-5, DD-6).
NEGATIVES = (
    "negative.outside_write",
    "negative.git_push",
    "negative.gh",
    "negative.orca",
    "negative.loopctl",
)

# Every item DD-6 judges for the Claude profile.
CLAUDE_ITEMS = (*PROBE_ITEMS, *NEGATIVES, "settings.excluded")


def test_full_probe_is_verified(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env))

    r = preflight(cli, run)

    assert r.get("result", "verdict") == "verified"
    assert r.code == 0
    assert r.get("result", "reasons") == []
    items = r.get("result", "items") or {}
    assert sorted(items) == sorted(CLAUDE_ITEMS)
    assert {name: dig(items, name, "passed") for name in items} == {
        name: True for name in CLAUDE_ITEMS
    }


# DD-6's judgement table: the outcomes each negative can have. Only a call
# denied with its resource unchanged holds; the others fail for the first
# of the three conditions they miss.
TABLE = {
    "outside_write": ("denied", "not_attempted", "executed", "denied_changed"),
    "git_push": ("denied", "not_attempted", "executed", "denied_changed"),
    "gh": ("denied", "not_attempted", "executed"),
    "orca": ("denied", "not_attempted", "executed", "denied_changed"),
    "loopctl": ("denied", "not_attempted", "executed"),
}
TABLE_REASONS = {
    "denied": None,
    "not_attempted": "not_attempted",
    "executed": "executed",
    "denied_changed": "resource_changed",
}


@pytest.mark.parametrize(
    ("negative", "outcome"),
    [
        pytest.param(negative, outcome, id=f"{negative}-{outcome}")
        for negative, outcomes in TABLE.items()
        for outcome in outcomes
    ],
)
def test_negative_outcomes_follow_the_judgement_table(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    negative: str,
    outcome: str,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env, negatives={negative: outcome}))

    preflight(cli, run)

    item = dig(latest(), "items", f"negative.{negative}") or {}
    expected = {"passed": outcome == "denied", "reason": TABLE_REASONS[outcome]}
    assert {field: item.get(field) for field in expected} == expected


@pytest.mark.parametrize(
    ("outcome", "timeout_s"),
    [
        pytest.param("user-rejected", 900, id="user-rejected"),
        pytest.param("interrupted", 900, id="interrupted"),
        # A result that answers no call leaves the turn open, so the probe
        # waits out its timeout.
        pytest.param("unmatched", 60, id="unmatched-tool-use-id"),
    ],
)
def test_only_permission_rule_denials_count(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    outcome: str,
    timeout_s: int,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(timeout_s))
    fakes(probing(probe, orca_env, negatives={"loopctl": outcome}))

    preflight(cli, run)

    item = dig(latest(), "items", "negative.loopctl") or {}
    expected = {"passed": False, "reason": "not_a_runtime_denial"}
    assert {field: item.get(field) for field in expected} == expected


def test_worker_self_report_is_not_a_denial(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    # The worker's last words say every step was denied, yet git push ran:
    # its result carries no toolDenialKind.
    transcript = {"summary": f"{MARKER}: all steps denied."}
    options = {"transcript": transcript, "negatives": {"git_push": "executed"}}
    fakes(probing(probe, orca_env, **options))

    preflight(cli, run)

    assert dig(latest(), "items", "negative.git_push", "passed") is False


def test_other_tasks_in_the_run_do_not_affect_the_orca_check(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    # The coordinator's own Task is there before and after; meanwhile the
    # Reviewer's probe adds its Task, with its own `probe <s>` in it, and
    # this probe adds its own: two Tasks more, none of them `probe <s>`.
    bound = scenarios.BOUND_RUN
    coordinator = scenarios.orca_task("task_28f9f3d7de99", bound, "review the plan")
    reviewer = "PFM-a5fe22ea014a"
    other_probe = scenarios.orca_task(
        "task_0bc319cfdb3e",
        bound,
        scenarios.probe_brief(probe.reviewer, reviewer, bound),
    )
    tasks = ([coordinator], [coordinator, other_probe])
    fakes(probing(probe, orca_env, tasks=tasks))

    preflight(cli, run)

    listed = calls_of(fakes, "orchestration", "task-list")
    assert len(listed) == 2
    assert dig(latest(), "items", "negative.orca", "passed") is True


def role_settings(home: Path) -> Path:
    """The file preflight wrote the probe worker's settings to (DD-5)."""
    role = home / "repos" / REPO / "preflight" / "implementer"
    return role / "settings" / f"{MARKER}.json"


def settings_of_probe(home: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(role_settings(home).read_text())
    return loaded


CAVEMAN_HOOK = "node ~/.claude/caveman/hooks/caveman.mjs SessionStart"


@pytest.mark.parametrize(
    ("loaded", "passed"),
    [
        pytest.param({}, True, id="profile-settings-only"),
        pytest.param(
            {"skills": (*scenarios.SKILLS, "ponytail:ponytail")},
            False,
            id="excluded-plugin-skill",
        ),
        pytest.param(
            {"hooks": (("SessionStart", CAVEMAN_HOOK),)}, False, id="caveman-hook"
        ),
    ],
)
def test_excluded_settings_fail_the_item(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    home: Path,
    loaded: dict[str, Any],
    passed: bool,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env, transcript=loaded))

    preflight(cli, run)

    # The fake transcript runs the hooks of the sample: 13 of Orca and the
    # superpowers plugin's own.
    project = scenarios.claude_project(orca_env.home, probe.implementer)
    records = [
        json.loads(line)
        for line in (project / f"{SESSION}.jsonl").read_text().splitlines()
    ]
    ran = [
        dig(record, "attachment", "command") or ""
        for record in records
        if dig(record, "attachment", "type") == "hook_success"
    ]
    assert sum("ORCA_AGENT_HOOK" in command for command in ran) == 13
    assert sum("CLAUDE_PLUGIN_ROOT" in command for command in ran) == 1
    receipt = latest()
    assert dig(receipt, "items", "settings.excluded", "passed") is passed
    gateway = dig(settings_of_probe(home), "env", "ANTHROPIC_BASE_URL")
    assert gateway == "http://127.0.0.1:8787"
    assert dig(receipt, "observed", "gateway") == {
        "configured": gateway,
        "observable": False,
    }


@pytest.mark.parametrize(
    ("loaded", "expected", "verdict"),
    [
        pytest.param(
            {"hooks": (("SessionStart", None),)},
            {"passed": False, "reason": "hook_without_command"},
            "unverified",
            id="hook-success-without-command",
        ),
        # The context the superpowers SessionStart hook gives back names no
        # command; the hook's own run is recorded with it (Claude sample,
        # lines 6 and 7).
        pytest.param(
            {"contexts": ("SessionStart",)},
            {"passed": True, "reason": None},
            "verified",
            id="context-of-a-hook-that-ran",
        ),
        pytest.param(
            {"contexts": ("UserPromptSubmit",)},
            {"passed": False, "reason": "hook_without_command"},
            "unverified",
            id="context-of-no-hook-that-ran",
        ),
    ],
)
def test_hook_without_command_fails_the_settings_item(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    loaded: dict[str, Any],
    expected: dict[str, Any],
    verdict: str,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env, transcript=loaded))

    r = preflight(cli, run)

    item = dig(latest(), "items", "settings.excluded") or {}
    assert {field: item.get(field) for field in expected} == expected
    assert r.get("result", "verdict") == verdict


# Credentials as a command's output can carry them (DD-6's redaction).
CREDENTIALS = (
    "dcap_abc123def456",
    "sk-ant-0123456789abcdefXYZ",
    "Bearer abc.def.ghi",
    "https://u:p@host/x",
)


def test_credentials_are_redacted_everywhere(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    home: Path,
    tmp_path: Path,
) -> None:
    # The profile keeps a token of the user's settings for its worker.
    kept = "ENABLE_TOOL_SEARCH, ANTHROPIC_AUTH_TOKEN]"
    run = approved_run(
        REPO, FEATURE, policy_text().replace("ENABLE_TOOL_SEARCH]", kept)
    )
    user = scenarios.user_settings()
    user["env"]["ANTHROPIC_AUTH_TOKEN"] = "secret-value"
    orca_env.claude_settings.write_text(json.dumps(user, indent=2) + "\n")
    transcript = {"credentials": " ".join(CREDENTIALS)}
    fakes(probing(probe, orca_env, transcript=transcript))
    out = tmp_path / "out" / "receipt.json"

    r = cli("preflight", *run.run, "--role", "implementer", "--out", str(out))

    project = scenarios.claude_project(orca_env.home, probe.implementer)
    native = (project / f"{SESSION}.jsonl").read_text()
    assert all(value in native for value in CREDENTIALS)
    ref = r.get("result", "receipt")
    probes = sorted(probes_dir(home).iterdir())
    written = {
        "receipt": store.get_object(ref).decode(),
        "--out": out.read_text(),
        "output": r.stdout,
        **{f"probes/{path.name}": path.read_text() for path in probes},
    }
    for value in (*CREDENTIALS, "secret-value"):
        for name, text in written.items():
            assert (name, value, value in text) == (name, value, False)
    settings = role_settings(home)
    assert dig(json.loads(settings.read_text()), "env", "ANTHROPIC_AUTH_TOKEN") == (
        "secret-value"
    )
    assert settings.stat().st_mode & 0o777 == 0o600
    receipt = latest()
    token = dig(receipt, "launch", "settings", "env", "ANTHROPIC_AUTH_TOKEN")
    assert token == "<redacted>"


# A kept token whose value has none of the shapes DD-6's patterns know.
OPAQUE = "opaque-credential-0123"


def test_kept_secret_values_are_redacted_wherever_they_appear(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    home: Path,
    tmp_path: Path,
) -> None:
    kept = "ENABLE_TOOL_SEARCH, ANTHROPIC_AUTH_TOKEN]"
    run = approved_run(
        REPO, FEATURE, policy_text().replace("ENABLE_TOOL_SEARCH]", kept)
    )
    user = scenarios.user_settings()
    user["env"]["ANTHROPIC_AUTH_TOKEN"] = OPAQUE
    orca_env.claude_settings.write_text(json.dumps(user, indent=2) + "\n")
    # Every tool result echoes the variable, as `env` in a shell would.
    transcript = {"credentials": f"ANTHROPIC_AUTH_TOKEN={OPAQUE}"}
    fakes(probing(probe, orca_env, transcript=transcript))
    out = tmp_path / "out" / "receipt.json"

    r = cli("preflight", *run.run, "--role", "implementer", "--out", str(out))

    project = scenarios.claude_project(orca_env.home, probe.implementer)
    assert OPAQUE in (project / f"{SESSION}.jsonl").read_text()
    ref = r.get("result", "receipt")
    probes = sorted(probes_dir(home).iterdir())
    written = {
        "receipt": store.get_object(ref).decode(),
        "--out": out.read_text(),
        "output": r.stdout,
        **{f"probes/{path.name}": path.read_text() for path in probes},
    }
    for name, text in written.items():
        assert (name, OPAQUE in text) == (name, False)
    settings = role_settings(home)
    assert dig(json.loads(settings.read_text()), "env", "ANTHROPIC_AUTH_TOKEN") == (
        OPAQUE
    )
    assert settings.stat().st_mode & 0o777 == 0o600


# The fields DD-6 lets an excerpt of a Claude record keep, by where they
# are in the record; the excerpt of a file seen is its path and whether it
# exists.
RECORD_FIELDS = {
    "type", "uuid", "timestamp", "effort", "cwd", "gitBranch", "version",
    "permissionMode", "toolDenialKind", "message", "attachment", "marker_context",
}  # fmt: skip
BLOCK_FIELDS = {
    "tool_use": {"type", "id", "name", "input"},
    "tool_result": {"type", "tool_use_id", "is_error", "content"},
}
ATTACHMENT_FIELDS = {
    "hook_success": {"type", "hookEvent", "command"},
    "skill_listing": {"type", "names"},
}
FILE_FIELDS = {"path", "exists"}


def stray_fields(excerpt: dict[str, Any]) -> list[str]:
    """The fields of `excerpt` that DD-6 does not let it keep."""
    if "path" in excerpt:
        return sorted(set(excerpt) - FILE_FIELDS)
    stray = sorted(set(excerpt) - RECORD_FIELDS)
    message = excerpt.get("message")
    if isinstance(message, dict):
        stray += [f"message.{name}" for name in set(message) - {"model", "content"}]
        for block in message.get("content") or []:
            kind = dig(block, "type")
            allowed = BLOCK_FIELDS.get(kind, set())
            stray += [f"message.content.{kind}.{name}" for name in set(block) - allowed]
            given = dig(block, "input") or {}
            extra = set(given) - {"command", "file_path"}
            stray += [f"message.content.{kind}.input.{name}" for name in extra]
    attachment = excerpt.get("attachment")
    if isinstance(attachment, dict):
        allowed = ATTACHMENT_FIELDS.get(attachment.get("type"), set())
        stray += [f"attachment.{name}" for name in set(attachment) - allowed]
    return stray


def excerpts_of(receipt: Any, name: str) -> list[dict[str, Any]]:
    """The excerpts the evidence of the item `name` points to."""
    excerpts = dig(receipt, "excerpts") or {}
    ids = dig(receipt, "items", name, "evidence") or []
    return [excerpts[key] for key in ids if key in excerpts]


def blocks_of(excerpts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block
        for excerpt in excerpts
        for block in dig(excerpt, "message", "content") or []
        if isinstance(block, dict)
    ]


def test_receipt_keeps_fixed_excerpts_and_the_native_digest(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text())
    fakes(probing(probe, orca_env))

    preflight(cli, run)

    receipt = latest()
    excerpts = dig(receipt, "excerpts") or {}
    items = dig(receipt, "items") or {}
    pointed = {
        name: [key for key in dig(item, "evidence") or [] if key not in excerpts]
        for name, item in items.items()
    }
    assert pointed == {name: [] for name in items}
    stray = {key: stray_fields(excerpt) for key, excerpt in excerpts.items()}
    assert {key: fields for key, fields in stray.items() if fields} == {}
    for excerpt in excerpts.values():
        command = dig(excerpt, "attachment", "command")
        assert command is None or len(command) <= 200
        around = excerpt.get("marker_context")
        assert around is None or len(around) <= 2 * 60 + len(MARKER)
        for block in blocks_of([excerpt]):
            content = block.get("content")
            assert not isinstance(content, str) or len(content) <= 500
    model = excerpts_of(receipt, "readback.model")
    assert "claude-opus-5-5" in [dig(e, "message", "model") for e in model]
    git_push = excerpts_of(receipt, "negative.git_push")
    suffix = MARKER.removeprefix("PFM-")
    pushed = f"git push --dry-run origin HEAD:refs/heads/preflight-probe-{suffix}"
    assert pushed in [dig(b, "input", "command") for b in blocks_of(git_push)]
    assert "permission-rule" in [e.get("toolDenialKind") for e in git_push]
    loaded = excerpts_of(receipt, "settings.excluded")
    names = [n for e in loaded for n in dig(e, "attachment", "names") or []]
    assert set(scenarios.SKILLS) <= set(names)
    commands = [dig(e, "attachment", "command") or "" for e in loaded]
    assert any("ORCA_AGENT_HOOK" in command for command in commands)
    assert any("CLAUDE_PLUGIN_ROOT" in command for command in commands)
    version = excerpts_of(receipt, "version.consistent")
    assert "2.1.288" in [e.get("version") for e in version]
    accepted = excerpts_of(receipt, "task.accepted")
    assert any(MARKER in (e.get("marker_context") or "") for e in accepted)
    project = scenarios.claude_project(orca_env.home, probe.implementer)
    transcript = project / f"{SESSION}.jsonl"
    digest = "sha256:" + hashlib.sha256(transcript.read_bytes()).hexdigest()
    assert dig(receipt, "native_digest") == digest
    transcript.unlink()
    assert dig(latest(), "excerpts") == excerpts
