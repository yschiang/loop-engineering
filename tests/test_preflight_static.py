"""preflight up to the probe: the approved policy's profiles and the
environment they need, judged without any worker, and the receipt, its
index and --out (design DD-3, DD-4 steps 0-5 and 13, DD-8)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import ApprovedRun, Clock, Fakes, OrcaEnv, ProbeRepo, Result, dig
from fakes import scenarios

from loopctl import receipts, store

Cli = Callable[..., Result]

REPO = scenarios.REPO
FEATURE = "orca-preflight"


def policy_text(change: Callable[[dict[str, Any]], None]) -> str:
    """The DD-2 example policy after `change` of its document."""
    document = yaml.safe_load(scenarios.POLICY)
    change(document)
    return yaml.safe_dump(document, sort_keys=False)


@pytest.fixture
def probe(probe_repo: Callable[..., ProbeRepo]) -> ProbeRepo:
    """The author's repo with both probe workspaces as linked worktrees."""
    return probe_repo()


def preflight(cli: Cli, run: ApprovedRun, role: str, *options: str) -> Result:
    return cli("preflight", *run.run, "--role", role, *options)


def stored(r: Result) -> Any:
    """The receipt the output names, read back from the store."""
    return json.loads(store.get_object(r.get("result", "receipt")))


def no_reviewer(document: dict[str, Any]) -> None:
    del document["profiles"]["reviewer"]


def no_implementer_model(document: dict[str, Any]) -> None:
    del document["profiles"]["implementer"]["model"]


@pytest.mark.parametrize(
    ("change", "role", "reasons"),
    [
        pytest.param(
            no_implementer_model, "implementer", ["profile_invalid:model"],
            id="implementer-without-model",
        ),
        pytest.param(no_reviewer, "reviewer", ["profile_missing"], id="no-reviewer"),
    ],
)  # fmt: skip
def test_invalid_profile_is_unverified_without_calling_tools(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    change: Callable[[dict[str, Any]], None],
    role: str,
    reasons: list[str],
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(change))
    fakes(scenarios.environment(probe))

    r = preflight(cli, run, role)

    assert r.get("blocked", "reasons") == reasons
    assert r.code == 3
    assert r.get("blocked", "kind") == "preflight_unverified"
    assert r.get("result", "verdict") == "unverified"
    assert fakes.calls() == []
    latest = receipts.latest(REPO, role)
    assert dig(latest, "verdict") == "unverified"
    assert latest == stored(r)


def test_malformed_approved_policy_is_unverified(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
) -> None:
    # The approval binds these very bytes, broken YAML and all.
    run = approved_run(REPO, FEATURE, "profiles: [implementer\n")
    fakes(scenarios.environment(probe))

    r = preflight(cli, run, "implementer")

    assert r.get("blocked", "reasons") == ["policy_invalid:yaml_error"]
    assert r.code == 3
    assert fakes.calls() == []


def same_model(document: dict[str, Any]) -> None:
    profiles = document["profiles"]
    reviewer, implementer = profiles["reviewer"], profiles["implementer"]
    reviewer["model"] = implementer["model"]
    assert reviewer["probe_effort"] != implementer["probe_effort"]


def test_same_model_makes_the_reviewer_unverified(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
) -> None:
    run = approved_run(REPO, FEATURE, policy_text(same_model))

    fakes(scenarios.environment(probe))
    reviewer = preflight(cli, run, "reviewer")
    fakes(scenarios.environment(probe))
    implementer = preflight(cli, run, "implementer")

    assert "model_not_distinct" in (reviewer.get("blocked", "reasons") or [])
    assert reviewer.code == 3
    assert reviewer.get("result", "items", "model.distinct", "passed") is False
    assert "model_not_distinct" not in (implementer.get("result", "reasons") or [])
    assert implementer.get("result", "reasons") is not None


@dataclass
class Setting:
    """What a case of test_missing_selected_tools_block_the_profile may
    take away: the fakes, the caller's Orca terminal and Claude settings,
    and the probe workspaces, linked or with the Reviewer in a clone."""

    fakes: Fakes
    orca: OrcaEnv
    monkeypatch: pytest.MonkeyPatch
    probe: ProbeRepo
    clone: ProbeRepo


Scenario = dict[str, list[dict[str, Any]]]


def orca_missing(s: Setting) -> Scenario:
    s.fakes.without("orca")
    return scenarios.environment(s.probe)


def orca_unreachable(s: Setting) -> Scenario:
    return scenarios.environment(s.probe, reachable=False)


def claude_missing(s: Setting) -> Scenario:
    s.fakes.without("claude")
    return scenarios.environment(s.probe)


def outside_orca_terminal(s: Setting) -> Scenario:
    s.monkeypatch.delenv("ORCA_TERMINAL_HANDLE")
    return scenarios.environment(s.probe)


def other_remote_only(s: Setting) -> Scenario:
    other = "github.com/someone-else/loop-engineering"
    repos = [
        scenarios.folder_repo(),
        scenarios.orca_repo(scenarios.REPO_ID, s.probe.author, other),
    ]
    return scenarios.environment(s.probe, repos=repos)


def no_engineer_workspace(s: Setting) -> Scenario:
    worktrees = [
        worktree
        for worktree in scenarios.orca_worktrees(s.probe)
        if worktree["displayName"] != "preflight-engineer"
    ]
    return scenarios.environment(s.probe, worktrees=worktrees)


def engineer_workspace_in_both_repos(s: Setting) -> Scenario:
    assert s.clone.clone is not None
    second = s.clone.clone.parent / "clone-workspaces" / "preflight-engineer"
    worktrees = [
        *scenarios.orca_worktrees(s.clone),
        scenarios.orca_worktree(scenarios.CLONE_REPO_ID, second, "preflight-engineer"),
    ]
    return scenarios.environment(s.clone, worktrees=worktrees)


def status_not_json(s: Setting) -> Scenario:
    return scenarios.environment(s.probe, status="Orca is starting, try again\n")


def user_settings_missing(s: Setting) -> Scenario:
    s.orca.claude_settings.unlink()
    return scenarios.environment(s.probe)


def user_settings_not_json(s: Setting) -> Scenario:
    s.orca.claude_settings.write_text('{"env": {\n')
    return scenarios.environment(s.probe)


def implementer_profile_without_model(s: Setting) -> Scenario:
    return scenarios.environment(s.probe)


@pytest.mark.parametrize(
    ("take_away", "role", "reason"),
    [
        pytest.param(orca_missing, "implementer", "transport_missing", id="a"),
        pytest.param(orca_unreachable, "implementer", "transport_unreachable", id="b"),
        pytest.param(claude_missing, "implementer", "runtime_missing", id="c"),
        pytest.param(
            outside_orca_terminal, "implementer", "not_in_orca_terminal", id="d"
        ),
        pytest.param(other_remote_only, "implementer", "repo_not_registered", id="e"),
        pytest.param(
            no_engineer_workspace, "implementer", "workspace_not_found", id="f"
        ),
        pytest.param(
            engineer_workspace_in_both_repos, "implementer", "workspace_ambiguous",
            id="g",
        ),
        pytest.param(
            status_not_json, "implementer", "unparseable:orca status", id="h"
        ),
        pytest.param(
            user_settings_missing, "implementer", "user_settings_unreadable", id="i"
        ),
        pytest.param(
            user_settings_not_json, "implementer", "user_settings_unreadable", id="j"
        ),
        pytest.param(
            no_engineer_workspace, "reviewer", "implementer_workspace_not_found",
            id="k",
        ),
        pytest.param(
            engineer_workspace_in_both_repos, "reviewer",
            "implementer_workspace_ambiguous", id="l",
        ),
        pytest.param(
            implementer_profile_without_model, "reviewer",
            "implementer_profile_invalid", id="m",
        ),
    ],
)  # fmt: skip
def test_missing_selected_tools_block_the_profile(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    monkeypatch: pytest.MonkeyPatch,
    probe_repo: Callable[..., ProbeRepo],
    take_away: Callable[[Setting], Scenario],
    role: str,
    reason: str,
) -> None:
    text = scenarios.POLICY
    if take_away is implementer_profile_without_model:
        text = policy_text(no_implementer_model)
    run = approved_run(REPO, FEATURE, text)
    setting = Setting(
        fakes, orca_env, monkeypatch, probe_repo(), probe_repo(reviewer="clone")
    )
    fakes(take_away(setting))

    r = preflight(cli, run, role)

    assert r.get("blocked", "reasons") == [reason]
    assert r.code == 3
    assert r.get("result", "verdict") == "unverified"


def test_reviewer_clone_with_the_same_remote_is_found(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe_repo: Callable[..., ProbeRepo],
) -> None:
    run = approved_run(REPO, FEATURE, scenarios.POLICY)
    clone = probe_repo(reviewer="clone")
    repos = scenarios.orca_repos(clone)
    by_path = {entry["path"]: entry for entry in repos}
    assert by_path[str(clone.author)]["gitRemoteIdentity"] == by_path[
        str(clone.clone)
    ]["gitRemoteIdentity"]
    fakes(scenarios.environment(clone))

    r = preflight(cli, run, "reviewer")

    reasons = r.get("result", "reasons")
    assert reasons is not None
    assert "workspace_not_found" not in reasons
    assert "implementer_workspace_not_found" not in reasons


def test_unselected_tools_are_never_called(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
) -> None:
    run = approved_run(REPO, FEATURE, scenarios.POLICY)
    called: dict[str, set[str]] = {}
    for role in ("implementer", "reviewer"):
        before = len(fakes.calls())
        fakes(scenarios.environment(probe))
        r = preflight(cli, run, role)
        assert r.code is not None, r
        called[role] = {call["tool"] for call in fakes.calls()[before:]}

    assert called["implementer"].isdisjoint({"herdr", "opencode", "codex"})
    assert called["reviewer"].isdisjoint({"herdr", "opencode", "claude"})
    assert {"orca", "claude"} <= called["implementer"]
    assert {"orca", "codex"} <= called["reviewer"]


RUN_CREATE = ["orchestration", "run-create"]


def run_creates(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in calls if call["argv"][:2] == RUN_CREATE]


def test_no_run_is_created_when_one_is_bound(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
) -> None:
    run = approved_run(REPO, FEATURE, scenarios.POLICY)

    fakes(scenarios.environment(probe, run=scenarios.BOUND_RUN))
    bound = preflight(cli, run, "implementer")
    first = len(fakes.calls())
    fakes(scenarios.environment(probe))
    unbound = preflight(cli, run, "implementer")

    assert run_creates(fakes.calls()[:first]) == []
    assert len(run_creates(fakes.calls()[first:])) == 1
    assert dig(stored(bound), "orca", "run") == scenarios.BOUND_RUN
    assert dig(stored(unbound), "orca", "run") == scenarios.CREATED_RUN


def test_out_writes_the_same_receipt(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    clock: Clock,
    home: Path,
    tmp_path: Path,
) -> None:
    run = approved_run(REPO, FEATURE, scenarios.POLICY)
    out = tmp_path / "evidence" / "implementer.json"

    fakes(scenarios.environment(probe))
    r = preflight(cli, run, "implementer", "--out", str(out))

    assert out.is_file()
    data = out.read_bytes()
    assert "sha256:" + hashlib.sha256(data).hexdigest() == r.get("result", "receipt")

    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)
    clock.sleep(60)
    fakes(scenarios.environment(probe))
    try:
        failed = preflight(
            cli, run, "implementer", "--out", str(readonly / "implementer.json")
        )
    finally:
        readonly.chmod(0o700)

    assert failed.code == 6
    assert failed.get("result", "error") == "io_error"
    assert failed.get("result", "op") == "write_out"
    assert failed.get("result", "committed") is True
    index = store.list_records(
        home / "repos" / REPO / "preflight" / "implementer" / "receipts"
    )
    assert len(index.items) == 2
    latest = receipts.latest(REPO, "implementer")
    assert latest == json.loads(store.get_object(index.items[-1]["receipt"]))
    assert dig(latest, "started_at") == clock.now()


def test_preflight_never_changes_the_feature_state(
    cli: Cli,
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    home: Path,
) -> None:
    run = approved_run(REPO, FEATURE, scenarios.POLICY)
    directory = home / "runs" / REPO / FEATURE
    state = (directory / "feature.json").read_bytes()
    history = sorted(path.name for path in (directory / "history").iterdir())
    revision = cli("status", *run.run).get("revision")

    for role in ("implementer", "reviewer"):
        fakes(scenarios.environment(probe))
        r = preflight(cli, run, role)
        assert r.get("result", "receipt") is not None, r

    assert (directory / "feature.json").read_bytes() == state
    assert sorted(path.name for path in (directory / "history").iterdir()) == history
    assert cli("status", *run.run).get("revision") == revision


# Holds the role's lock through a second open file description for the rest
# of the process, as another preflight of the role would (flock is per open
# file description, so the preflight run after it cannot take it either).
HOLD_LOCK = """\
import fcntl as _fcntl, os as _os
_os.makedirs({directory!r}, exist_ok=True)
_held = _os.open(_os.path.join({directory!r}, "lock"), _os.O_RDWR | _os.O_CREAT, 0o600)
_fcntl.flock(_held, _fcntl.LOCK_EX)
"""


def test_concurrent_preflight_for_one_role_is_refused(
    cli: Cli,
    cli_proc: Callable[..., Result],
    approved_run: Callable[..., ApprovedRun],
    orca_env: OrcaEnv,
    fakes: Fakes,
    probe: ProbeRepo,
    home: Path,
) -> None:
    run = approved_run(REPO, FEATURE, scenarios.POLICY)
    role = home / "repos" / REPO / "preflight" / "implementer"
    fakes(scenarios.environment(probe))

    r = cli_proc(
        "preflight", *run.run, "--role", "implementer",
        prelude=HOLD_LOCK.format(directory=str(role)),
    )  # fmt: skip

    assert r.code == 1
    assert r.get("result", "error") == "preflight_running"
    assert store.list_records(role / "receipts").items == []
    assert receipts.latest(REPO, "implementer") is None
