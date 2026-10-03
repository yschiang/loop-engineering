"""preflight's probe of the Claude profile: the launch in an Orca terminal,
the probe task, the wait, the readback from the transcript, the versions,
the stop and worker_done (design DD-4 steps 6-12a, DD-5, DD-6, DD-7)."""

from __future__ import annotations

import errno
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

from loopctl import receipts, store

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
    """claude_probe for this test's workspaces and ids."""
    return scenarios.claude_probe(
        probe, orca_env.home, MARKER, str(SESSION), **options
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


def test_probe_is_not_verified_until_judgement_is_complete(
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

    assert r.get("result", "verdict") == "unverified"
    assert r.get("blocked", "reasons") == ["judgement_incomplete"]
    assert r.code == 3


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
    # Once the terminal exists, its record cannot be written; in the second
    # row neither can the record of the stop.
    options = {"unwritable_probes": probes, "writable_on_close": writable_on_close}
    fakes(probing(probe, orca_env, **options))
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
