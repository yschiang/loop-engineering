"""Task 2.10: the controller main loop across persisted state, outbox, fake runtime/GitHub, import, integrate, gates."""

import json
import subprocess
import sys

import pytest

from delivery.authority import Authority
from delivery.loop import Context, run_until_idle, start_run
from delivery.store import Store
from delivery.versions import version_key

from .fake_agents import AgentRuntime, RepoGitHub

BRANCH = "delivery/s1"
G1 = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml={junit}", "tests"]
T1 = {"tests": {"tests/test_add.py": "import sys\nsys.path.insert(0, 'src')\nfrom app import add\n\n\n"
                                     "def test_add():\n    assert add(1, 2) == 3\n"},
      "impl": {"src/app.py": "def add(a, b):\n    return a + b\n"}}
# The fix's test fails inside the test body (AttributeError), a behavior Red; an import-time failure would be a
# collection error and the controller rightly refuses it as Red.
FIX = {"tests": {"tests/test_sub.py": "import sys\nsys.path.insert(0, 'src')\nimport app\n\n\n"
                                     "def test_sub():\n    assert app.sub(3, 1) == 2\n"},
       "impl": {"src/app.py": "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"}}
FINDING = {"category": "spec_ac", "problem": "sub() missing for AC-X02", "basis": "AC-X02", "expected": "sub exists"}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    r = tmp_path / "ctl"
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    for k, v in (("user.email", "c@x"), ("user.name", "controller")):
        git(r, "config", k, v)
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("def add(a, b):\n    return 0\n")
    (r / ".gitignore").write_text("__pycache__/\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    git(r, "branch", BRANCH)
    return r


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += 1.0
        return self.t


def ctx(tmp_path, ctl, runtime, github, isolation=True, run_id="r1", skills=None, impl_isolation=True):
    authority = Authority(tmp_path / "home", "repo", "yschiang/orca-delivery#1")
    authority.start(str(ctl), str(tmp_path / "run"), run_id)
    return Context(run_dir=tmp_path / "run", ctl_repo=ctl, attempts_root=tmp_path / "attempts", branch=BRANCH,
                   runtime=runtime, github=github,
                   policy={"g1_argv": G1, "excludes": [".env*"],
                           "reviewer": {"model": "gpt-r"},
                           "ci": {"required": [{"name": "test", "app": "github-actions", "source": "head"}],
                                  "allow_non_success": []}},
                   isolation={"status": "verified", "profile_digest": "P"} if isolation else None,
                   sandbox_profile_digest="P" if isolation else None, authority=authority,
                   implementer_isolation={"status": "verified" if impl_isolation else "unverified"},
                   installed_skills=skills if skills is not None else {"superpowers:test-driven-development": "bf1b"},
                   clock=Clock())


def begin(c, approval=True, ticket="yschiang/orca-delivery#1", deps=None, carried=0):
    return start_run(c, "r1", "yschiang/orca-delivery#1",
                     [{"task_id": "t1", "ac_ids": ["AC-X01"], "scope": ["src", "tests"], "spec": T1}],
                     "plan-v1", {"plan": "plan-v1", "issue_body": "d1"},
                     {"decision_id": "DEC-1", "plan_version": "plan-v1"} if approval else None, ticket=ticket,
                     dependencies=deps or [], skills={"superpowers:test-driven-development": "bf1b"},
                     carried_active_seconds=carried)


def test_full_loop_with_review_finding_fix_and_rereview_reaches_pass_across_restarts(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "changes_required", "findings": [FINDING]},
                               {"verdict": "clean", "close": ["F-0001"]}], fix_spec=FIX)
    gh = RepoGitHub(ctl)
    c = ctx(tmp_path, ctl, rt, gh)
    begin(c)
    trail = run_until_idle(c)  # every step reloads run.json from disk
    state = Store(c.run_dir).load().state
    assert state["phase"] == "ready_for_acceptance", (trail, state["blockers"])
    tip = git(ctl, "rev-parse", f"refs/heads/{BRANCH}")
    assert state["versions"]["head_sha"] == tip and state["versions"]["pr_number"] == 1
    assert state["current_pass"]["version_key"] == version_key(state["versions"])
    assert [t["status"] for t in state["tasks"]] == ["succeeded", "succeeded"]
    assert state["tasks"][1]["batch_id"] == "b1" and state["budget"]["correction_rounds_used"] == 1
    f = state["registry"]["findings"]["F-0001"]
    assert f["status"] == "resolved" and f["fix_commits"] and f["closure"]["actor_kind"] == "reviewer"
    assert [e["task_id"] for e in state["integration"]["log"]] == ["t1", "fix-b1"]
    assert (rt.creates, rt.sends) == (4, 4)  # 2 implementer + 2 reviewer dispatches, none repeated
    g1 = state["gates"]["g1"]
    assert g1["status"] == "passed" and set(g1["tasks"]) == {"t1", "fix-b1"}
    assert all(t["red"][0]["replay"]["failing_ids"] == t["red"][0]["failing_ids"] for t in state["tasks"])
    assert not Store(c.run_dir).load().blocked  # every referenced blob is durable
    assert git(ctl, "rev-parse", f"refs/heads/{BRANCH}") == gh.pr_head(1)


def test_missing_red_evidence_never_defaults_to_pass(tmp_path, ctl):
    c = ctx(tmp_path, ctl, AgentRuntime(reviews=[], skip_red=True), RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "blocked"
    assert state["gates"]["g1"]["status"] == "missing"
    assert state["current_pass"] is None


def test_unverified_reviewer_isolation_blocks_instead_of_passing(tmp_path, ctl):
    c = ctx(tmp_path, ctl, AgentRuntime(reviews=[{"verdict": "clean"}]), RepoGitHub(ctl), isolation=False)
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "blocked" and state["gates"]["g2"]["status"] == "unknown"
    assert state["current_pass"] is None


def test_ci_failure_waits_for_review_and_joins_one_batch(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}, {"verdict": "clean"}], fix_spec=FIX)
    gh = RepoGitHub(ctl, ci=lambda sha, n: "failure" if n == 1 else "success")
    c = ctx(tmp_path, ctl, rt, gh)
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["batches"][0]["items"]["ci"] and state["budget"]["correction_rounds_used"] == 1


def test_no_approval_means_no_dispatch(tmp_path, ctl):
    rt = AgentRuntime(reviews=[])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c, approval=False)
    run_until_idle(c)
    assert Store(c.run_dir).load().state["phase"] == "awaiting_approval"
    assert rt.creates == 0


def test_fenced_dispatch_blocks_with_reason_instead_of_crashing(tmp_path, ctl):
    rt = AgentRuntime(reviews=[])
    rt.faults = {"send": "drop"}  # prompt never reaches the runtime; the attempt is fenced
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "blocked"
    assert state["blockers"][-1]["kind"] == "dispatch_failed"
    assert state["blockers"][-1]["op_state"] == "fenced"


BUGGY = {"tests": T1["tests"], "impl": {"src/app.py": "def add(a, b):\n    return a - b\n"}}


def test_fixable_g1_failure_returns_to_producing_task_without_a_correction_round(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}], attempt_specs={"t1-a1": BUGGY})
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "ready_for_acceptance", state["blockers"]
    assert [a["attempt_id"] for a in state["tasks"][0]["attempts"]] == ["t1-a1", "t1-a2"]
    assert state["budget"]["correction_rounds_used"] == 0 and state["batches"] == []
    second = next(a for a in rt.assignments if a["attempt_id"] == "t1-a2")
    assert second["g1_return"]["reasons"] and "regression" in " ".join(second["g1_return"]["reasons"])


def test_invalid_historical_red_blocks_instead_of_rerouting(tmp_path, ctl):
    rt = AgentRuntime(reviews=[], tamper_red=True)
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "blocked" and state["blockers"][-1]["kind"] == "g1_not_passed"
    assert len(state["tasks"][0]["attempts"]) == 1


@pytest.mark.parametrize("setup,kind", [
    ("other_owner", "authority_not_held"),
    ("no_ticket", "no_ticket"),
    ("skill_drift", "skill_pin_mismatch"),
    ("impl_sandbox", "implementer_isolation_unverified"),
    ("budget", "active_budget_exhausted"),
])
def test_dispatch_guards_block_before_any_dispatch(tmp_path, ctl, setup, kind):
    rt = AgentRuntime(reviews=[])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl), skills={"superpowers:test-driven-development": "CHANGED"}
            if setup == "skill_drift" else None, impl_isolation=setup != "impl_sandbox")
    if setup == "other_owner":
        c.authority.abandon("r1", {"kind": "abandon_run", "actor": "u", "reason": "moved", "evidence": ["x"]})
        c.authority.start(str(tmp_path / "other"), str(tmp_path / "other-run"), "r-other")
    begin(c, ticket=None if setup == "no_ticket" else "yschiang/orca-delivery#1",
          carried=4 * 3600 if setup == "budget" else 0)  # limit already reached
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "blocked" and state["blockers"][-1]["kind"] == kind
    assert rt.creates == 0


def test_unmerged_dependency_waits_without_dispatch_then_proceeds_when_merged(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}])
    gh = RepoGitHub(ctl)
    c = ctx(tmp_path, ctl, rt, gh)
    base = git(ctl, "rev-parse", "main")
    begin(c, deps=[{"feature": "F0", "version": "v9", "accepted_versions": ["v9"]}])
    assert run_until_idle(c)[-1] == "waiting_dependency" and rt.creates == 0
    gh.dependencies["F0"] = {"merged": True, "merge_commit": base}
    run_until_idle(c)
    assert Store(c.run_dir).load().state["phase"] == "ready_for_acceptance"


def test_active_time_is_accumulated_from_dispatch_to_result(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c, carried=100)
    run_until_idle(c)
    b = Store(c.run_dir).load().state["budget"]
    assert b["carried_seconds"] == 100 and b["activities"]
    assert all(a["end"] is not None for a in b["activities"].values())


def test_integration_is_persisted_before_its_effect_and_converges_after_crash(tmp_path, ctl):
    from delivery.loop import step

    rt = AgentRuntime(reviews=[{"verdict": "clean"}])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    trail = []
    while not trail or trail[-1] != "integrate_registered":
        trail.append(step(c))
        assert len(trail) < 20, trail
    store = Store(c.run_dir)
    state = store.load().state
    op = next(o for o in state["operations"].values() if o["kind"] == "integrate")
    assert op["state"] == "pending" and git(ctl, "rev-parse", f"refs/heads/{BRANCH}") == op["t0"]
    # Crash after the ref moved but before the snapshot recorded it.
    git(ctl, "fetch", "-q", op["clone"], f"+HEAD:refs/delivery/attempts/{op['attempt_id']}")
    git(ctl, "update-ref", f"refs/heads/{BRANCH}", git(op["clone"], "rev-parse", "HEAD"), op["t0"])
    op["state"] = "in_flight"
    store.commit(state)
    run_until_idle(c)
    final = Store(c.run_dir).load().state
    assert final["phase"] == "ready_for_acceptance"
    assert [e["task_id"] for e in final["integration"]["log"]] == ["t1"]
    iop = next(o for o in final["operations"].values() if o["kind"] == "integrate")
    assert iop["state"] == "succeeded" and iop["result"]["already_integrated"] is True


def test_review_is_published_to_pr_and_issue_through_the_outbox(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "changes_required", "findings": [FINDING]},
                               {"verdict": "clean", "close": ["F-0001"]}], fix_spec=FIX)
    gh = RepoGitHub(ctl)
    c = ctx(tmp_path, ctl, rt, gh)
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert len(gh.comments["pr"]) == 2 and len(gh.comments["issue"]) == 2
    assert "F-0001" in gh.comments["pr"][0] and "changes_required" in gh.comments["pr"][0]
    assert "https://gh/pr#c1" in gh.comments["issue"][0]
    pubs = [o for o in state["operations"].values() if o["op_id"].startswith("op-pub-")]
    assert len(pubs) == 4 and all(o["state"] == "succeeded" for o in pubs)


def advance_main(ctl, path="README.md", text="docs\n"):
    git(ctl, "checkout", "-q", "main")
    (ctl / path).write_text(text)
    git(ctl, "add", "-A")
    git(ctl, "commit", "-qm", "main moves")
    git(ctl, "checkout", "-q", "--detach")


def test_base_only_change_after_pass_invalidates_and_rechecks_through_the_loop(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}, {"verdict": "clean"}])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    first = Store(c.run_dir).load().state["current_pass"]["version_key"]
    advance_main(ctl)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "ready_for_acceptance"
    assert state["current_pass"]["version_key"] != first
    assert state["pass_history"][0]["invalidated_at"]
    assert state["gates"]["g1"]["derived"]["rule"] == "R-base"
    assert state["versions"]["base_tip"] == git(ctl, "rev-parse", "main")
    assert len(state["reviews"]) == 2


def test_base_conflict_opens_a_correction_batch(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    advance_main(ctl, "src/app.py", "def add(a, b):\n    return 99\n")
    from delivery.loop import step

    assert step(c) == "versions_changed"  # the fix dispatch that follows is ordinary correction work
    state = Store(c.run_dir).load().state
    assert state["phase"] == "correcting" and state["tasks"][-1]["batch_id"] == state["batches"][-1]["batch_id"]
    assert state["batches"][-1]["items"]["base_conflict"] is True
    assert state["budget"]["correction_rounds_used"] == 1


def test_contract_change_waits_for_adoption_then_needs_new_review(tmp_path, ctl):
    from delivery.decisions import apply_decision

    rt = AgentRuntime(reviews=[{"verdict": "clean"}, {"verdict": "clean"}])
    gh = RepoGitHub(ctl)
    c = ctx(tmp_path, ctl, rt, gh)
    begin(c)
    run_until_idle(c)
    gh.bindings["issue_body"] = "d2"
    assert run_until_idle(c)[-1] == "awaiting_approval"
    store = Store(c.run_dir)
    state = store.load().state
    assert state["current_pass"] is None and state["candidates"]["issue_body"]["content_digest"] == "d2"
    apply_decision(state, {"decision_id": "DEC-7", "kind": "adopt_binding", "actor": "user", "actor_kind": "human",
                           "source": "chat:9", "reason": "new AC wording", "created_at": "t",
                           "subject": {"role": "issue_body"}})
    store.commit(state)
    run_until_idle(c)
    final = Store(c.run_dir).load().state
    assert final["phase"] == "ready_for_acceptance" and final["versions"]["bindings"]["issue_body"] == "d2"
    assert len(final["reviews"]) == 2


def test_raw_red_green_and_replay_outputs_are_durable_blobs(tmp_path, ctl):
    import shutil

    rt = AgentRuntime(reviews=[{"verdict": "clean"}])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    shutil.rmtree(c.run_dir / "inbox")  # worker area gone; the controller's copies must remain
    store = Store(c.run_dir)
    state = store.load().state
    red = state["tasks"][0]["red"][0]
    assert b"test_add" in store.blob_path(red["raw"]["stdout"]).read_bytes()
    assert b"test_add" in store.blob_path(red["replay"]["raw"]["stdout"]).read_bytes()
    green = json.loads(store.blob_path(state["gates"]["g1"]["evidence"][0]).read_bytes())
    assert store.blob_path(green["raw"]["stdout"]).exists()
    assert not store.load().blocked


DOCS = {"tests": {}, "impl": {"README.md": "usage\n"}}


def begin_na(c, spec):
    return start_run(c, "r1", "yschiang/orca-delivery#1",
                     [{"task_id": "t1", "ac_ids": ["AC-X01"], "scope": ["src", "tests"], "spec": T1},
                      {"task_id": "d1", "ac_ids": [], "scope": ["README.md", "src"], "spec": spec,
                       "change_class": "na_requested", "na_reason": "docs only"}],
                     "plan-v1", {"plan": "plan-v1", "issue_body": "d1"},
                     {"decision_id": "DEC-1", "plan_version": "plan-v1"}, ticket="yschiang/orca-delivery#1",
                     skills={"superpowers:test-driven-development": "bf1b"})


def test_docs_only_task_gets_independent_na_eligibility_before_g1(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}], na_verdicts=["accepted"])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    c.policy["na_doc_globs"] = ["docs/**", "*.md", "**/*.md"]
    begin_na(c, DOCS)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "ready_for_acceptance", state["blockers"]
    d1 = state["tasks"][1]
    assert d1["na"]["status"] == "accepted" and d1["na"]["diff_digest"] == d1["diff_digest"]
    assert state["gates"]["g1"]["tasks"]["d1"]["na"] == "accepted"
    assert any(a["role"] == "na_reviewer" for a in rt.assignments) is False  # reviewer is not an implementer


def test_na_request_touching_code_is_rejected_without_eligibility_review(tmp_path, ctl):
    rt = AgentRuntime(reviews=[], na_verdicts=[])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    c.policy["na_doc_globs"] = ["docs/**", "*.md", "**/*.md"]
    begin_na(c, {"tests": {}, "impl": {"src/extra.py": "X = 1\n"}})
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "blocked" and state["tasks"][1]["na"]["status"] == "rejected"
    assert "prefilter" in state["tasks"][1]["na"]["reason"]
    assert rt.creates == 2  # two implementer dispatches, no eligibility review


def fix_spec(n):
    return {"tests": {f"tests/test_fix{n}.py": "import sys\nsys.path.insert(0, 'src')\nimport app\n\n\n"
                      f"def test_fix{n}():\n    assert app.f{n}() == {n}\n"},
            "impl": {f"src/f{n}.py": "", "src/app.py": "def add(a, b):\n    return a + b\n\n\n"
                     + "".join(f"def f{i}():\n    return {i}\n\n\n" for i in range(1, n + 1))}}


def test_finding_that_survives_two_rechecks_blocks_before_a_third_round(tmp_path, ctl):
    again = {**FINDING, "matches": "F-0001"}
    rt = AgentRuntime(reviews=[{"verdict": "changes_required", "findings": [FINDING]},
                               {"verdict": "changes_required", "findings": [again]},
                               {"verdict": "changes_required", "findings": [again]}],
                      attempt_specs={"fix-b1-a1": fix_spec(1), "fix-b2-a1": fix_spec(2)})
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    run_until_idle(c)
    state = Store(c.run_dir).load().state
    assert state["phase"] == "blocked" and state["blockers"][-1]["kind"] == "recurrence"
    assert state["registry"]["findings"]["F-0001"]["failed_rechecks"] == 2
    assert state["budget"]["correction_rounds_used"] == 2


def test_every_state_changing_step_is_recorded_once_in_events(tmp_path, ctl):
    rt = AgentRuntime(reviews=[{"verdict": "clean"}])
    c = ctx(tmp_path, ctl, rt, RepoGitHub(ctl))
    begin(c)
    trail = run_until_idle(c)
    run_until_idle(c)  # resting steps add nothing
    events = [json.loads(x) for x in (c.run_dir / "events.jsonl").read_text().splitlines()]
    steps = [e["step"] for e in events]
    assert {"dispatch_registered", "integrated", "g1_passed", "pass"} <= set(steps)
    assert len({e["id"] for e in events}) == len(events)
    assert len(events) == sum(1 for t in trail if t not in ("waiting_result",))
    assert Store(c.run_dir).load().state["pending_history"] == []
