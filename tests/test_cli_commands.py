"""CLI wiring (design §1): each command calls the core and leaves real state; missing S2 adapters exit 3."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from delivery.store import Store

EXE = str(Path(sys.executable).parent / "delivery")


def run(*args, cwd=None):
    return subprocess.run([EXE, *map(str, args)], capture_output=True, text=True, cwd=cwd, check=False)


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    r = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    for k, v in (("user.email", "c@x"), ("user.name", "c")):
        git(r, "config", k, v)
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("def add(a, b):\n    return 0\n")
    (r / ".gitignore").write_text("__pycache__/\n.delivery/\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r


def started(tmp_path, repo):
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps([{"task_id": "t1", "ac_ids": ["AC-X01"], "scope": ["src", "tests"]}]))
    assert run("init", "--repo", repo).returncode == 0
    p = run("start", "--repo", repo, "--feature", "o/r#1", "--run-id", "r1", "--branch", "delivery/s1",
            "--tasks", tasks, "--plan-version", "P1", "--state-home", tmp_path / "home")
    assert p.returncode == 0, p.stderr
    return repo / ".delivery" / "runs" / "r1"


def test_init_writes_policy_once(repo):
    assert run("init", "--repo", repo).returncode == 0
    assert (repo / "workflow.yaml").read_text().startswith("schema_version: 1")
    again = run("init", "--repo", repo)
    assert again.returncode == 1 and "exists" in again.stderr


def test_start_creates_run_under_authority_and_second_clone_is_refused(tmp_path, repo):
    run_dir = started(tmp_path, repo)
    state = Store(run_dir).load().state
    assert state["phase"] == "awaiting_approval" and state["tasks"][0]["task_id"] == "t1"
    other = tmp_path / "clone2"
    git(tmp_path, "clone", "-q", str(repo), str(other))
    p = run("start", "--repo", other, "--feature", "o/r#1", "--run-id", "r2", "--branch", "delivery/s1",
            "--tasks", tmp_path / "tasks.json", "--plan-version", "P1", "--state-home", tmp_path / "home",
            "--repo-id", str(repo))
    assert p.returncode == 1 and str(run_dir) in p.stdout + p.stderr


def test_decide_records_human_decision_and_rejects_agents(tmp_path, repo):
    run_dir = started(tmp_path, repo)
    bad = run("decide", "--run-dir", run_dir, "--kind", "approve_plan", "--actor", "bot", "--actor-kind", "agent",
              "--source", "x", "--reason", "y", "--subject", '{"plan_version": "P1"}')
    assert bad.returncode == 1
    ok = run("decide", "--run-dir", run_dir, "--kind", "approve_plan", "--actor", "user", "--source", "chat:1",
             "--reason", "approve", "--subject", '{"plan_version": "P1"}')
    assert ok.returncode == 0, ok.stderr
    assert Store(run_dir).load().state["phase"] == "implementing"


def test_evidence_run_saves_record_and_raw_output(tmp_path, repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("import sys\nsys.path.insert(0, 'src')\nimport app\n\n\n"
                                              "def test_add():\n    assert app.add(1, 2) == 3\n")
    out = tmp_path / "ev"
    p = run("evidence", "run", "--kind", "red", "--task", "t1", "--attempt", "a1", "--cwd", repo, "--t0",
            git(repo, "rev-parse", "HEAD"), "--scope", "src,tests", "--out", out, "--",
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml={junit}", "tests")
    assert p.returncode == 0, p.stderr
    rec = json.loads((out / "red.json").read_text())
    assert rec["status"] == "test_failed" and rec["failing_ids"] == ["tests.test_a::test_add"]
    assert (out / "red.stdout").exists()


def test_submit_result_is_write_once(tmp_path):
    inbox = tmp_path / "inbox" / "a1"
    f1, f2 = tmp_path / "r1.json", tmp_path / "r2.json"
    f1.write_text(json.dumps({"attempt_id": "a1", "execution_status": "succeeded"}))
    f2.write_text(json.dumps({"attempt_id": "a1", "execution_status": "failed"}))
    assert run("submit-result", "--inbox", inbox, "--file", f1).returncode == 0
    second = run("submit-result", "--inbox", inbox, "--file", f2)
    assert second.returncode == 1
    assert json.loads((inbox / "result.json").read_text())["execution_status"] == "succeeded"


def test_adopt_routes_from_facts(tmp_path, repo):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"kind": "adopt", "owner_handoff": True, "unknown_writers": ["pid 7"],
                                 "sources": {"conflicts": [], "unreadable": []}, "has_plan": True, "d11": True,
                                 "tasks_done": True, "g1_verified": False, "fixed_base": True,
                                 "historical_red": True}))
    run("init", "--repo", repo)
    p = run("adopt", "--repo", repo, "--feature", "o/r#2", "--run-id", "r9", "--facts", facts,
            "--state-home", tmp_path / "home")
    assert p.returncode == 0, p.stderr
    state = Store(repo / ".delivery" / "runs" / "r9").load().state
    assert state["phase"] == "blocked" and state["blockers"][0]["kind"] == "unknown_writer"


def test_resume_reconcile_and_preflight_report_missing_s2_adapters(tmp_path, repo):
    run_dir = started(tmp_path, repo)
    run("decide", "--run-dir", run_dir, "--kind", "approve_plan", "--actor", "user", "--source", "chat:1",
        "--reason", "approve", "--subject", '{"plan_version": "P1"}')
    before = (run_dir / "run.json").read_bytes()
    for cmd in (["resume", "--run-dir", run_dir], ["reconcile", "--run-dir", run_dir]):
        p = run(*cmd)
        assert p.returncode == 3 and "not available" in p.stderr, (cmd, p.stderr)
    assert Store(run_dir).load().state["phase"] == "implementing"
    assert (run_dir / "run.json").read_bytes() == before or Store(run_dir).load().state["tasks"][0]["lease"] is None
    pf = run("preflight", "--repo", repo, "--profile", "implementer")
    assert pf.returncode == 3
    report = json.loads(pf.stdout)
    assert report["runtime"]["status"] == "unavailable" and report["isolation"]["status"] in ("verified", "unverified")
