"""Task 2.10: the controller main loop across persisted state, outbox, fake runtime/GitHub, import, integrate, gates."""

import subprocess
import sys

import pytest

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


def ctx(tmp_path, ctl, runtime, github, isolation=True):
    return Context(run_dir=tmp_path / "run", ctl_repo=ctl, attempts_root=tmp_path / "attempts", branch=BRANCH,
                   runtime=runtime, github=github,
                   policy={"g1_argv": G1, "excludes": [".env*"],
                           "reviewer": {"model": "gpt-r"},
                           "ci": {"required": [{"name": "test", "app": "github-actions", "source": "head"}],
                                  "allow_non_success": []}},
                   isolation={"status": "verified", "profile_digest": "P"} if isolation else None,
                   sandbox_profile_digest="P" if isolation else None)


def begin(c, approval=True):
    return start_run(c, "r1", "yschiang/orca-delivery#1",
                     [{"task_id": "t1", "ac_ids": ["AC-X01"], "scope": ["src", "tests"], "spec": T1}],
                     "plan-v1", {"plan": "plan-v1", "issue_body": "d1"},
                     {"decision_id": "DEC-1", "plan_version": "plan-v1"} if approval else None)


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
