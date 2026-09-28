"""M-DEC d1, d2, d4–d6, d7a, d8–d10: `register` and `decide` records (design §2, §3).

T2.2 owns the record layer only: resolve_read / resolve_operation / budget_extension
effects are T2.3 / T7.1 (o1, w10, b2–b6); accept / return effects are T6.2 (d7b).
Phases that later tasks produce (implementing, pass) are set up with store.commit.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loopctl import clock, store
from loopctl.cli import main

FEATURE = "F-1"
FIXED = datetime(2026, 9, 28, 9, 30, tzinfo=UTC)
HEAD = "a" * 40
ROOT = Path(__file__).resolve().parents[1]


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fakes) -> Path:
    home = tmp_path / "loopctl-home"
    monkeypatch.setenv("LOOPCTL_HOME", str(home))
    monkeypatch.setattr(clock, "now", lambda: FIXED)
    return home


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The feature's repo with native documents; locators are relative to it (cwd)."""
    repo = tmp_path / "repo"
    for rel, text in {
        "docs/superpowers/plans/P03-ingest.md": "# P03 ingest plan\n\n- T1: AC-1 via test_ingest\n",
        "docs/superpowers/plans/P03-draft.md": "# Draft from Project Lead\n",
        "openspec/specs/ingest/spec.md": "# Ingest spec\n\n#### Scenario: AC-1\n",
        "docs/sa/P03-confirmation.md": "SA confirmed by user for P03\n",
        "workflow.yaml": "required_checks: [unit-linux]\n",
        "evidence/client.log": "connect: ECONNREFUSED before request was sent\n",
    }.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    monkeypatch.chdir(repo)
    return repo


PLAN = "docs/superpowers/plans/P03-ingest.md"
DRAFT = "docs/superpowers/plans/P03-draft.md"
SPEC = "openspec/specs/ingest/spec.md"


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def started(capsys, feature: str = FEATURE) -> str:
    """init + claim; returns the owner token."""
    code, out = run(
        capsys, "init", "--repo", "yschiang/loop-engineering", "--repo-id", "R_1",
        "--feature", feature, "--issue", "7",
    )
    assert code == 0, out
    code, out = run(capsys, "claim", "--feature", feature, "--actor", "orchestrate")
    assert code == 0, out
    return str(out["result"]["token"])


def register_plan(
    capsys, token: str, locator: str = PLAN, producer: str = "implementer",
    calibrated: str | None = SPEC, version: str = "v1",
) -> tuple[int, dict]:
    argv = [
        "register", "plan", "--feature", FEATURE, f"--token={token}", "--locator", locator,
        "--version", version, "--producer", producer,
    ]
    if calibrated:
        argv += ["--calibrated-from", calibrated]
    return run(capsys, *argv)


def decide(capsys, token: str | None, kind: str, **fields: str | bool | None) -> tuple[int, dict]:
    values: dict[str, str | bool | None] = {
        "feature": FEATURE, "token": token, "id": f"{kind}-1", "actor": "human:alice",
        "target": PLAN, "version": "v1", "reason": "reviewed with the user",
    }
    values.update(fields)
    argv = ["decide", kind]
    for key, value in values.items():
        if value is True:
            argv.append(f"--{key.replace('_', '-')}")
        elif value is not None and value is not False:
            # `--opt=value`: a claim token may start with '-' (token_urlsafe).
            argv.append(f"--{key.replace('_', '-')}={value}")
    return run(capsys, *argv)


def approve(capsys, token: str, **fields: str) -> dict:
    code, out = decide(capsys, token, "approve_plan", **fields)
    assert code == 0, out
    return out


def next_of(capsys) -> dict:
    code, out = run(capsys, "next", "--feature", FEATURE)
    assert code == 0, out
    return dict(out["next"])


def at_phase(phase: str, **extra: object) -> int:
    """Simulate a phase a later task produces (T2.3 implementing, T6.2 pass)."""
    rev, _ = store.load(FEATURE)
    return store.commit(FEATURE, rev, f"test:{phase}", lambda s: {**s, "phase": phase, **extra})


# --- d1 --------------------------------------------------------------------------------


def test_d1_direct_init_and_plan_registration_stays_in_planning_without_dispatch(
    capsys, home, repo, fakes
):
    token = started(capsys)
    assert next_of(capsys) == {
        "action": "human", "blockers": ["plan_not_registered"], "decision_kinds": []
    }

    code, out = register_plan(capsys, token)
    assert code == 0, out
    assert out["result"]["plan"]["producer"] == "implementer"

    code, out = run(capsys, "status", "--feature", FEATURE)
    assert code == 0 and out["result"]["phase"] == "planning"
    assert next_of(capsys) == {
        "action": "human", "blockers": ["plan_not_approved"], "decision_kinds": ["approve_plan"]
    }
    _, state = store.load(FEATURE)
    assert state["approval"] is None
    assert state["attempts"] == {} and state["writes"] == {}
    assert fakes.calls() == []


# --- d2 --------------------------------------------------------------------------------

APPROVAL_SOURCES = ["silence", "timeout", "agent", "sa_only", "draft_plan", "calibrated_human"]


@pytest.mark.parametrize("source", APPROVAL_SOURCES)
def test_d2_only_a_human_approve_plan_on_a_calibrated_plan_is_an_approval(
    capsys, home, repo, fakes, monkeypatch, source
):
    token = started(capsys)
    code, out = register_plan(
        capsys, token, *((DRAFT, "project_lead", None) if source == "draft_plan" else ())
    )
    assert code == 0, out

    if source == "timeout":
        monkeypatch.setattr(clock, "now", lambda: FIXED + timedelta(days=30))
    elif source == "agent":
        code, out = decide(capsys, token, "approve_plan", actor="agent:implementer")
        assert (code, out["result"]["error"]) == (1, "actor_not_human")
    elif source == "sa_only":
        code, out = run(
            capsys, "register", "binding", "--feature", FEATURE, f"--token={token}",
            "--role", "sa", "--locator", "docs/sa/P03-confirmation.md", "--version", "sa-1",
        )
        assert code == 0, out
        code, out = decide(capsys, token, "sa_confirm", target="docs/sa/P03-confirmation.md")
        assert (code, out["result"]["error"]) == (2, "unsupported")
    elif source == "draft_plan":
        code, out = decide(capsys, token, "approve_plan", target=DRAFT)
        assert (code, out["result"]["error"]) == (1, "plan_not_calibrated")
    elif source == "calibrated_human":
        out = approve(capsys, token)
        record = out["result"]["decision"]
        assert {k: record[k] for k in ("id", "kind", "actor", "at", "target", "version", "reason")} == {
            "id": "approve_plan-1", "kind": "approve_plan", "actor": "human:alice",
            "at": FIXED.isoformat(), "target": PLAN, "version": "v1",
            "reason": "reviewed with the user",
        }

    _, state = store.load(FEATURE)
    nxt = next_of(capsys)
    if source == "calibrated_human":
        assert state["phase"] == "approved"
        assert state["approval"]["decision"] == "approve_plan-1"
        assert state["approval"]["plan"] == {
            "locator": PLAN, "version": "v1", "digest": sha(repo / PLAN),
            "producer": "implementer", "calibrated_from": SPEC,
        }
        assert nxt["blockers"] != ["plan_not_approved"]
    else:
        assert state["approval"] is None
        assert state["phase"] == "planning"
        assert state["decisions"] == {}
        assert nxt["action"] == "human"
        expected = "plan_not_calibrated" if source == "draft_plan" else "plan_not_approved"
        assert nxt["blockers"] == [expected]
    assert state["attempts"] == {} and state["writes"] == {}
    assert fakes.calls() == []


# --- d4 --------------------------------------------------------------------------------


def test_d4_scope_change_while_implementing_revokes_approval_and_stops_the_whole_run(
    capsys, home, repo, fakes
):
    token = started(capsys)
    register_plan(capsys, token)
    approve(capsys, token)
    at_phase("implementing")

    code, out = decide(
        capsys, token, "scope_change", target="AC-1", version="v1",
        reason="AC-1 must also cover retries",
    )
    assert code == 0, out
    _, state = store.load(FEATURE)
    assert state["phase"] == "awaiting_approval"
    assert state["approval"] is None
    assert state["decisions"]["scope_change-1"]["kind"] == "scope_change"
    assert next_of(capsys) == {
        "action": "human", "blockers": ["plan_not_approved"], "decision_kinds": ["approve_plan"]
    }

    # The unchanged plan is the old contract: approving it again is refused (design §8
    # "approve_plan (new digest)"; AC-O07).
    rev_before, _ = store.load(FEATURE)
    code, out = decide(capsys, token, "approve_plan", id="approve_plan-2")
    assert (code, out["result"].get("error")) == (1, "plan_superseded")
    assert out["result"]["scope_change"] == "scope_change-1"
    rev, state = store.load(FEATURE)
    assert rev == rev_before
    assert state["approval"] is None and state["phase"] == "awaiting_approval"
    assert "approve_plan-2" not in state["decisions"]

    # The run continues only after the revised plan is registered and approved.
    (repo / PLAN).write_text("# P03 ingest plan\n\n- T1: AC-1 via test_ingest, test_retry\n")
    code, out = register_plan(capsys, token, version="v2")
    assert code == 0, out
    approve(capsys, token, id="approve_plan-3", version="v2", reason="approved after scope change")
    _, state = store.load(FEATURE)
    assert state["phase"] == "approved"
    assert state["approval"]["decision"] == "approve_plan-3"
    assert state["approval"]["plan"]["version"] == "v2"
    assert fakes.calls() == []


def test_d4_reregistering_the_superseded_plan_binding_does_not_make_it_approvable(
    capsys, home, repo, fakes
):
    token = started(capsys)
    register_plan(capsys, token)
    approve(capsys, token)
    at_phase("implementing")
    code, out = decide(capsys, token, "scope_change", target="AC-1", reason="retries too")
    assert code == 0, out

    for locator in (PLAN, "docs/superpowers/plans/P03-copy.md"):  # same version and bytes
        (repo / locator).write_bytes((repo / PLAN).read_bytes())
        code, out = register_plan(capsys, token, locator=locator)
        assert code == 0, out
        rev_before, _ = store.load(FEATURE)
        code, out = decide(capsys, token, "approve_plan", id=f"approve-{locator}", target=locator)
        assert (code, out["result"].get("error")) == (1, "plan_superseded")
        rev, state = store.load(FEATURE)
        assert rev == rev_before and state["approval"] is None

    # Same bytes under a new version is a new plan binding (Lead ruling: version/digest).
    code, out = register_plan(capsys, token, version="v2")
    assert code == 0, out
    approve(capsys, token, id="approve_plan-2", version="v2")
    assert store.load(FEATURE)[1]["phase"] == "approved"
    assert fakes.calls() == []


# --- d5 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actor", "use_token", "code", "error"),
    [
        ("session:claude-parent-7", True, 1, "actor_not_human"),
        ("agent:project_lead", True, 1, "actor_not_human"),
        ("role:project_lead", True, 1, "actor_not_human"),
        ("project_lead", True, 1, "actor_not_human"),
        ("human:alice", "wrong", 4, "not_owner"),
        ("human:alice", False, 4, "not_owner"),
    ],
)
def test_d5_runtime_parent_or_project_lead_marker_cannot_approve(
    capsys, home, repo, fakes, actor, use_token, code, error
):
    token = started(capsys)
    register_plan(capsys, token)
    rev_before, _ = store.load(FEATURE)
    tok = token if use_token is True else ("not-the-token" if use_token == "wrong" else None)

    got, out = decide(capsys, tok, "approve_plan", actor=actor)
    assert (got, out["ok"], out["result"]["error"]) == (code, False, error)
    rev, state = store.load(FEATURE)
    assert rev == rev_before
    assert state["approval"] is None and state["decisions"] == {}
    assert fakes.calls() == []


# --- d6 --------------------------------------------------------------------------------


def test_d6_native_plan_and_spec_are_registered_in_place_and_read_back(
    capsys, home, repo, fakes
):
    token = started(capsys)
    before = snapshot(repo)

    code, out = register_plan(capsys, token)
    assert code == 0, out
    code, out = run(
        capsys, "register", "binding", "--feature", FEATURE, f"--token={token}",
        "--role", "spec", "--locator", SPEC, "--version", "spec-3",
    )
    assert code == 0, out

    _, state = store.load(FEATURE)
    plan = state["plan"]
    assert (plan["locator"], plan["version"], plan["digest"]) == (PLAN, "v1", sha(repo / PLAN))
    assert (plan["producer"], plan["calibrated_from"]) == ("implementer", SPEC)
    assert store.get_object(plan["content"][store.OBJECT_KEY]) == (repo / PLAN).read_bytes()
    spec = state["versions"]["bindings"]["spec"]
    assert (spec["locator"], spec["version"], spec["digest"]) == (SPEC, "spec-3", sha(repo / SPEC))
    assert store.get_object(spec["content"][store.OBJECT_KEY]) == (repo / SPEC).read_bytes()

    assert snapshot(repo) == before  # nothing renamed, moved or added in the repo
    assert state["writes"] == {} and state["attempts"] == {}  # a task is not made a PR
    assert fakes.calls() == []


def test_d6_unreadable_locator_or_digest_mismatch_is_rejected(capsys, home, repo, fakes):
    token = started(capsys)
    rev_before, _ = store.load(FEATURE)
    code, out = register_plan(capsys, token, locator="docs/missing.md")
    assert (code, out["result"]["error"]) == (1, "locator_unreadable")
    code, out = run(
        capsys, "register", "binding", "--feature", FEATURE, f"--token={token}", "--role",
        "spec", "--locator", SPEC, "--version", "s", "--digest", "sha256:" + "0" * 64,
    )
    assert (code, out["result"]["error"]) == (1, "digest_mismatch")
    code, out = run(
        capsys, "register", "plan", "--feature", FEATURE, "--token", "nope",
        "--locator", PLAN, "--version", "v1", "--producer", "implementer",
    )
    assert (code, out["result"]["error"]) == (4, "not_owner")
    assert store.load(FEATURE)[0] == rev_before


def test_d6_unreadable_plan_with_a_digest_is_rejected_and_never_approvable(
    capsys, home, repo, fakes
):
    """A digest does not stand in for the plan's content: the adopted plan must be read
    back (AC-O03) and an unreadable required reference stops the run (AC-O04)."""
    token = started(capsys)
    rev_before, _ = store.load(FEATURE)
    missing = "docs/superpowers/plans/P03-missing.md"
    code, out = run(
        capsys, "register", "plan", "--feature", FEATURE, f"--token={token}",
        "--locator", missing, "--version", "v1", "--digest", "sha256:" + "1" * 64,
        "--producer", "implementer", "--calibrated-from", SPEC,
    )
    assert (code, out["result"].get("error")) == (1, "locator_unreadable")
    rev, state = store.load(FEATURE)
    assert rev == rev_before and state["plan"] is None

    code, out = decide(capsys, token, "approve_plan", target=missing)
    assert (code, out["result"]["error"]) == (1, "plan_not_registered")
    _, state = store.load(FEATURE)
    assert state["approval"] is None and state["phase"] == "planning"
    assert fakes.calls() == []


def test_registering_a_changed_plan_after_approval_needs_a_new_approve_plan(
    capsys, home, repo, fakes
):
    token = started(capsys)
    register_plan(capsys, token)
    approve(capsys, token)
    (repo / PLAN).write_text("# P03 ingest plan\n\n- T1: AC-1\n- T2: AC-2\n")

    code, out = register_plan(capsys, token, version="v2")
    assert code == 0, out
    assert out["result"]["approval_invalidated"] is True
    _, state = store.load(FEATURE)
    assert state["approval"] is None and state["phase"] == "awaiting_approval"
    code, out = decide(capsys, token, "approve_plan", id="approve_plan-2")  # stale version v1
    assert (code, out["result"]["error"]) == (1, "plan_version_mismatch")
    approve(capsys, token, id="approve_plan-3", version="v2")
    assert store.load(FEATURE)[1]["approval"]["plan"]["digest"] == sha(repo / PLAN)


@pytest.mark.parametrize(
    "change",
    [
        {"version": "v2"},
        {"producer": "project_lead"},
        {"calibrated": "docs/sa/P03-confirmation.md"},
        {"locator": "docs/superpowers/plans/P03-copy.md"},
    ],
    ids=["version", "producer", "calibrated_from", "locator"],
)
def test_reregistering_the_same_plan_bytes_with_another_binding_revokes_approval(
    capsys, home, repo, fakes, change
):
    """Approval binds locator, version, producer and calibration source, not only the
    digest (AC-O06): the same bytes under another binding need a new approve_plan."""
    token = started(capsys)
    register_plan(capsys, token)
    approve(capsys, token)
    if "locator" in change:
        (repo / change["locator"]).write_bytes((repo / PLAN).read_bytes())

    code, out = register_plan(capsys, token, **change)
    assert code == 0, out
    _, state = store.load(FEATURE)
    assert state["plan"]["digest"] == sha(repo / PLAN)  # same bytes
    assert out["result"]["approval_invalidated"] is True
    assert state["approval"] is None and state["phase"] == "awaiting_approval"
    blocker = "plan_not_calibrated" if "producer" in change else "plan_not_approved"
    assert next_of(capsys)["blockers"] == [blocker]
    assert fakes.calls() == []


def test_reregistering_the_identical_plan_binding_keeps_approval(capsys, home, repo, fakes):
    token = started(capsys)
    register_plan(capsys, token)
    approve(capsys, token)

    code, out = register_plan(capsys, token)
    assert code == 0, out
    assert out["result"]["approval_invalidated"] is False
    _, state = store.load(FEATURE)
    assert state["phase"] == "approved"
    assert state["approval"]["decision"] == "approve_plan-1"


# --- d7a -------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["return", "accept"])
@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"actor": "agent:implementer"}, "actor_not_human"),
        ({"actor": None}, "missing_fields"),
        ({"version": None}, "missing_fields"),
        ({"reason": None}, "missing_fields"),
        ({"reason": ""}, "missing_fields"),
    ],
)
def test_d7a_return_and_accept_records_reject_agents_and_missing_fields(
    capsys, home, repo, fakes, kind, fields, error
):
    token = started(capsys)
    at_phase("pass", acceptance={"status": "pending", "version_key": "vk-1"})
    rev_before, _ = store.load(FEATURE)

    code, out = decide(capsys, token, kind, **{"target": "vk-1", "version": "vk-1", **fields})
    assert (code, out["result"]["error"]) == (1, error)
    rev, state = store.load(FEATURE)
    assert rev == rev_before and state["decisions"] == {}
    assert fakes.calls() == []


def test_d7a_accept_without_a_current_pass_is_rejected(capsys, home, repo, fakes):
    token = started(capsys)
    register_plan(capsys, token)
    rev_before, _ = store.load(FEATURE)
    code, out = decide(capsys, token, "accept", target="vk-1", version="vk-1")
    assert (code, out["result"]["error"]) == (1, "no_pass")
    at_phase("pass", acceptance={"status": "pending", "version_key": "vk-2"})
    rev_pass, _ = store.load(FEATURE)
    code, out = decide(capsys, token, "accept", target="vk-1", version="vk-1")
    assert (code, out["result"]["error"]) == (1, "version_not_current")
    assert store.load(FEATURE)[0] == rev_pass == rev_before + 1


# --- d8 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["decide", "adopt"],
        ["decide", "delegate"],
        ["decide", "adopt", "--feature", FEATURE, "--id", "x", "--actor", "human:alice",
         "--target", "F-1", "--version", "v1", "--reason", "take over"],
        ["decide", "delegate", "--feature", FEATURE, "--id", "x", "--actor", "human:alice",
         "--target", "project_lead", "--version", "v1", "--reason", "delegate"],
        ["adopt", "--feature", FEATURE],
        ["delegate", "--feature", FEATURE],
    ],
)
def test_d8_adopt_and_delegate_are_unsupported_with_zero_state_change(
    capsys, home, repo, fakes, argv
):
    token = started(capsys)
    before = snapshot(home)
    if argv[0] == "decide" and "--feature" in argv:
        argv = [*argv, f"--token={token}"]

    code, out = run(capsys, *argv)
    assert out["ok"] is False
    if argv[0] == "decide":
        assert (code, out["result"]["error"]) == (2, "unsupported")
        assert out["result"]["kind"] == argv[1]
    else:
        assert (code, out["result"]["error"]) == (2, "usage")
    assert snapshot(home) == before
    assert fakes.calls() == []


# --- d9 --------------------------------------------------------------------------------

READ_KEY = f"ci:yschiang/loop-engineering:{HEAD}"


def with_pending_recovery() -> None:
    """State T2.3 would leave behind: an exhausted read key and an unknown op."""
    rev, _ = store.load(FEATURE)
    store.commit(
        FEATURE, rev, "test:recovery",
        lambda s: {
            **s,
            "read_budget": {READ_KEY: {"consecutive_failures": 3}},
            "writes": {"op-7": {"kind": "pr_ensure", "status": "unknown"}},
            "blockers": [f"read_exhausted:{READ_KEY}", "write_unknown:op-7"],
        },
    )


RECOVERY = {
    "resolve_read": {"target": READ_KEY, "version": HEAD},
    "resolve_operation": {
        "target": "op-7", "version": HEAD, "not_delivered": True,
        "evidence": "evidence/client.log",
    },
}


@pytest.mark.parametrize("kind", sorted(RECOVERY))
@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"actor": "agent:orchestrate"}, "actor_not_human"),
        ({"reason": None}, "missing_fields"),
        ({"target": None}, "missing_fields"),
    ],
)
def test_d9_recovery_decisions_reject_agents_and_missing_reason_or_target(
    capsys, home, repo, fakes, kind, fields, error
):
    token = started(capsys)
    with_pending_recovery()
    rev_before, _ = store.load(FEATURE)
    code, out = decide(capsys, token, kind, **{**RECOVERY[kind], **fields})
    assert (code, out["result"]["error"]) == (1, error)
    rev, state = store.load(FEATURE)
    assert rev == rev_before and state["decisions"] == {}
    assert fakes.calls() == []


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("resolve_read", RECOVERY["resolve_read"]),
        ("resolve_operation", RECOVERY["resolve_operation"]),
        ("resolve_operation", {"target": "op-7", "version": HEAD, "bind": "pr:41",
                               "evidence": "evidence/client.log"}),
    ],
)
def test_d9_complete_human_recovery_decision_is_only_recorded(
    capsys, home, repo, fakes, kind, fields
):
    token = started(capsys)
    with_pending_recovery()
    _, before = store.load(FEATURE)

    code, out = decide(capsys, token, kind, **fields)
    assert code == 0, out
    _, state = store.load(FEATURE)
    record = state["decisions"][f"{kind}-1"]
    assert (record["actor"], record["target"], record["at"]) == (
        "human:alice", fields["target"], FIXED.isoformat()
    )
    if kind == "resolve_operation":
        mode = "bind" if "bind" in fields else "not_delivered"
        assert record["resolution"]["mode"] == mode
        assert store.get_object(record["evidence"][store.OBJECT_KEY]) == (
            repo / "evidence/client.log"
        ).read_bytes()
    # Only the decision record changed: budgets, ops and blockers are the effect owner's.
    for field in ("read_budget", "writes", "blockers", "observations", "phase", "budget"):
        assert state[field] == before[field], field
    assert fakes.calls() == []  # 0 external writes, 0 fetch


def test_d9_resolve_operation_needs_exactly_one_resolution_and_a_known_op(
    capsys, home, repo, fakes
):
    token = started(capsys)
    with_pending_recovery()
    rev_before, _ = store.load(FEATURE)
    base = RECOVERY["resolve_operation"]
    for fields, error in [
        ({**base, "not_delivered": False}, "resolution_required"),
        ({**base, "bind": "pr:41"}, "resolution_required"),
        ({**base, "evidence": None}, "missing_fields"),
        ({**base, "target": "op-404"}, "unknown_target"),
    ]:
        code, out = decide(capsys, token, "resolve_operation", **fields)
        assert (code, out["result"]["error"]) == (1, error), fields
    code, out = decide(capsys, token, "resolve_read", target="pr:404", version=HEAD)
    assert (code, out["result"]["error"]) == (1, "unknown_target")
    assert store.load(FEATURE)[0] == rev_before


# --- d10 -------------------------------------------------------------------------------

EXTENSIONS = ["active:30", "rounds:+1", "attempts:T1:+1", f"ci_wait:{HEAD}"]


def test_d10_budget_extension_records_each_target_without_touching_policy_or_counters(
    capsys, home, repo, fakes
):
    token = started(capsys)
    with_pending_recovery()
    rev, state = store.load(FEATURE)
    store.commit(FEATURE, rev, "test:budget", lambda s: {**s, "budget": {"active_used_s": 5400}})
    _, before = store.load(FEATURE)
    policy_before = (ROOT / "workflow.yaml").read_bytes(), (repo / "workflow.yaml").read_bytes()

    for n, target in enumerate(EXTENSIONS):
        code, out = decide(
            capsys, token, "budget_extension", id=f"ext-{n}", target=target, version=HEAD,
            reason="CI runner outage acknowledged",
        )
        assert code == 0, out

    _, state = store.load(FEATURE)
    assert [state["decisions"][f"ext-{n}"]["target"] for n in range(4)] == EXTENSIONS
    assert all(state["decisions"][f"ext-{n}"]["kind"] == "budget_extension" for n in range(4))
    for field in ("budget", "read_budget", "writes", "attempts", "batches", "blockers", "phase"):
        assert state[field] == before[field], field
    assert ((ROOT / "workflow.yaml").read_bytes(), (repo / "workflow.yaml").read_bytes()) == (
        policy_before
    )
    assert fakes.calls() == []


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"reason": None}, "missing_fields"),
        ({"target": "wallclock:30"}, "invalid_target"),
        ({"target": "active:-5"}, "invalid_target"),
        ({"target": "rounds:+2"}, "invalid_target"),
        ({"target": "ci_wait:not-a-sha"}, "invalid_target"),
        ({"actor": "agent:orchestrate"}, "actor_not_human"),
    ],
)
def test_d10_budget_extension_rejects_missing_reason_unknown_target_and_agents(
    capsys, home, repo, fakes, fields, error
):
    token = started(capsys)
    rev_before, _ = store.load(FEATURE)
    code, out = decide(
        capsys, token, "budget_extension", **{"target": "active:30", "version": HEAD, **fields}
    )
    assert (code, out["result"]["error"]) == (1, error)
    rev, state = store.load(FEATURE)
    assert rev == rev_before and state["decisions"] == {}


# --- record layer: idempotence and the remaining first-slice kinds ----------------------


def test_resending_the_same_decision_is_idempotent_and_a_reused_id_is_rejected(
    capsys, home, repo, fakes, monkeypatch
):
    token = started(capsys)
    register_plan(capsys, token)
    first = approve(capsys, token)
    monkeypatch.setattr(clock, "now", lambda: FIXED + timedelta(minutes=5))

    code, out = decide(capsys, token, "approve_plan")
    assert code == 0, out
    assert out["revision"] == first["revision"]
    assert out["result"]["duplicate"] is True
    assert out["result"]["decision"]["at"] == FIXED.isoformat()

    code, out = decide(capsys, token, "handoff", id="approve_plan-1", target="human:bob")
    assert (code, out["result"]["error"]) == (1, "decision_id_conflict")
    assert store.load(FEATURE)[0] == first["revision"]


def with_registry() -> None:
    rev, _ = store.load(FEATURE)
    store.commit(
        FEATURE, rev, "test:registry",
        lambda s: {**s, "findings": {"FND-1": {"category": "preference", "status": "open"}}},
    )


OTHER_KINDS = {
    "revise": {"target": "base_integration", "version": HEAD},
    "resolve_finding": {"target": "FND-1", "version": HEAD},
    "waive_finding": {"target": "FND-1", "version": HEAD},
    "reclassify_finding": {"target": "FND-1", "version": HEAD, "category": "correctness_security"},
    "handoff": {"target": "human:bob", "version": "v1"},
}


@pytest.mark.parametrize("kind", sorted(OTHER_KINDS))
def test_other_first_slice_kinds_are_recorded_by_humans_only(capsys, home, repo, fakes, kind):
    token = started(capsys)
    with_registry()
    _, before = store.load(FEATURE)
    code, out = decide(capsys, token, kind, actor="agent:reviewer", **OTHER_KINDS[kind])
    assert (code, out["result"]["error"]) == (1, "actor_not_human")

    code, out = decide(capsys, token, kind, **OTHER_KINDS[kind])
    assert code == 0, out
    _, state = store.load(FEATURE)
    assert state["decisions"][f"{kind}-1"]["target"] == OTHER_KINDS[kind]["target"]
    for field in ("findings", "phase", "approval", "blockers"):
        assert state[field] == before[field], field


def test_finding_decisions_need_a_known_finding_and_a_valid_category(capsys, home, repo, fakes):
    token = started(capsys)
    with_registry()
    rev_before, _ = store.load(FEATURE)
    code, out = decide(capsys, token, "waive_finding", target="FND-404", version=HEAD)
    assert (code, out["result"]["error"]) == (1, "unknown_target")
    code, out = decide(
        capsys, token, "reclassify_finding", target="FND-1", version=HEAD, category="style"
    )
    assert (code, out["result"]["error"]) == (1, "invalid_category")
    assert store.load(FEATURE)[0] == rev_before


def test_policy_change_binds_the_registered_policy_digest(capsys, home, repo, fakes):
    token = started(capsys)
    code, out = decide(
        capsys, token, "policy_change", target="workflow.yaml", version=sha(repo / "workflow.yaml")
    )
    assert (code, out["result"]["error"]) == (1, "policy_not_registered")
    code, out = run(
        capsys, "register", "policy", "--feature", FEATURE, f"--token={token}",
        "--locator", "workflow.yaml", "--version", "p1",
    )
    assert code == 0, out
    code, out = decide(
        capsys, token, "policy_change", id="pc-2", target="workflow.yaml",
        version="sha256:" + "0" * 64,
    )
    assert (code, out["result"]["error"]) == (1, "policy_digest_mismatch")
    code, out = decide(
        capsys, token, "policy_change", id="pc-3", target="workflow.yaml",
        version=sha(repo / "workflow.yaml"),
    )
    assert code == 0, out
    assert store.load(FEATURE)[1]["versions"]["policy"]["digest"] == sha(repo / "workflow.yaml")
