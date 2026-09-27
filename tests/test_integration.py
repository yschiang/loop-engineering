"""Task 2.9 (DR-05): integrate on real git - order, fencing, crash convergence, scope (AC-G08, D04)."""

import subprocess

import pytest

from delivery.gates import evaluate_g1
from delivery.integration import integrate

BRANCH = "delivery/s1"
SCOPE = ["src", "tests"]


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def ctl(tmp_path):
    r = tmp_path / "ctl"
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    for k, v in (("user.email", "t@x"), ("user.name", "t")):
        git(r, "config", k, v)
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("x = 0\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    git(r, "branch", BRANCH)
    return r


def attempt(tmp_path, ctl, name, path="src/app.py", text="x = 1\n"):
    c = tmp_path / name
    git(tmp_path, "clone", "-q", "--no-hardlinks", "--branch", BRANCH, str(ctl), str(c))
    for k, v in (("user.email", "w@x"), ("user.name", "w")):
        git(c, "config", k, v)
    t0 = git(c, "rev-parse", "HEAD")
    f = c / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(c, "add", "-A")
    git(c, "commit", "-qm", f"work {name}")
    return c, t0, git(c, "rev-parse", "HEAD")


def st(task, lease):
    return {"tasks": {task: {"lease": lease}}, "integration": {"branch": BRANCH, "log": []}, "blockers": []}


def tip(ctl):
    return git(ctl, "rev-parse", f"refs/heads/{BRANCH}")


def test_two_tasks_integrate_in_order_and_second_starts_from_first(tmp_path, ctl):
    s = st("t1", "a1")
    c1, t0_1, a1 = attempt(tmp_path, ctl, "a1")
    assert integrate(str(ctl), s, "t1", "a1", str(c1), t0_1, SCOPE, BRANCH)["status"] == "succeeded"
    s["tasks"]["t2"] = {"lease": "a2"}
    c2, t0_2, a2 = attempt(tmp_path, ctl, "a2", "src/b.py", "y = 2\n")
    assert t0_2 == a1
    assert integrate(str(ctl), s, "t2", "a2", str(c2), t0_2, SCOPE, BRANCH)["status"] == "succeeded"
    assert tip(ctl) == a2
    assert [(e["task_id"], e["from"], e["to"]) for e in s["integration"]["log"]] == [("t1", t0_1, a1), ("t2", a1, a2)]


def test_stale_attempt_is_fenced_and_never_touches_the_branch(tmp_path, ctl):
    s = st("t1", "a2")
    c1, t0, _ = attempt(tmp_path, ctl, "a1")
    before = tip(ctl)
    out = integrate(str(ctl), s, "t1", "a1", str(c1), t0, SCOPE, BRANCH)
    assert out["status"] == "rejected" and "lease" in out["reason"]
    assert tip(ctl) == before


def test_crash_before_update_ref_redoes_and_after_update_ref_converges(tmp_path, ctl):
    s = st("t1", "a1")
    c1, t0, a1 = attempt(tmp_path, ctl, "a1")
    git(ctl, "fetch", "-q", str(c1), "HEAD:refs/delivery/attempts/a1")  # crashed after fetch, ref still T0
    assert integrate(str(ctl), s, "t1", "a1", str(c1), t0, SCOPE, BRANCH)["status"] == "succeeded"
    s2 = st("t1", "a1")  # snapshot lost: resume sees ref == A
    out = integrate(str(ctl), s2, "t1", "a1", str(c1), t0, SCOPE, BRANCH)
    assert out["status"] == "succeeded" and out["already_integrated"] is True
    assert tip(ctl) == a1


def test_branch_at_a_third_value_blocks(tmp_path, ctl):
    s = st("t1", "a1")
    c1, t0, _ = attempt(tmp_path, ctl, "a1")
    (ctl / "src" / "other.py").write_text("z\n")
    git(ctl, "add", "-A")
    git(ctl, "commit", "-qm", "unexpected")
    git(ctl, "update-ref", f"refs/heads/{BRANCH}", "HEAD")
    out = integrate(str(ctl), s, "t1", "a1", str(c1), t0, SCOPE, BRANCH)
    assert out["status"] == "blocked"
    assert s["blockers"][-1]["kind"] == "integration_conflict"


def test_changes_outside_scope_are_rejected(tmp_path, ctl):
    s = st("t1", "a1")
    c1, t0, _ = attempt(tmp_path, ctl, "a1", "outside.txt", "no\n")
    before = tip(ctl)
    out = integrate(str(ctl), s, "t1", "a1", str(c1), t0, SCOPE, BRANCH)
    assert out["status"] == "rejected" and "outside.txt" in out["reason"]
    assert tip(ctl) == before


def test_integrated_head_regression_fails_g1(tmp_path, ctl):
    s = st("t1", "a1")
    c1, t0, _ = attempt(tmp_path, ctl, "a1")
    integrate(str(ctl), s, "t1", "a1", str(c1), t0, SCOPE, BRANCH)
    green = {"head": tip(ctl), "status": "failed", "producer": {"tool": "controller-runner"},
             "failing_ids": ["tests.test_y::test_other"], "passing_ids": []}
    assert evaluate_g1([], green, tip(ctl), lambda a, b: True)["status"] == "failed"
