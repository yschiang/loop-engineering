"""Task 1.2 (DR-04): real-git tests for the baseline+overlay Red snapshot and evidence runner."""

import hashlib
import os
import subprocess
import sys

import pytest

from delivery.runner import Evidence, Refusal, Snapshot, run_evidence, snapshot_worktree

SCOPE = ["src", "tests"]
EXCL = [".env*", "*.pem", "*.key"]
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml={junit}", "tests"]
FAILING_TEST = "import sys\nsys.path.insert(0, 'src')\nfrom app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    r = tmp_path / "w"
    (r / "src").mkdir(parents=True)
    (r / "tests").mkdir()
    git(tmp_path, "init", "-q", str(r))
    git(r, "config", "user.email", "t@x")
    git(r, "config", "user.name", "t")
    (r / "src" / "app.py").write_text("def add(a, b):\n    return 0\n")
    (r / "README.md").write_text("base\n")
    (r / ".gitignore").write_text("__pycache__/\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r


def t0(r):
    return git(r, "rev-parse", "HEAD")


def worker_state(r):
    status = git(r, "--no-optional-locks", "status", "--porcelain", "-uall")  # read-only: must not refresh index
    return hashlib.sha256((r / ".git" / "index").read_bytes()).hexdigest(), status


def files(r, commit):
    return set(git(r, "ls-tree", "-r", "--name-only", commit).split())


def snap(r, base, ref="refs/delivery/red/t/a/1"):
    before = worker_state(r)
    s = snapshot_worktree(str(r), base, SCOPE, EXCL, ref)
    assert worker_state(r) == before  # worker index bytes and status never change
    return s


def test_untracked_only_new_test_is_captured(repo):
    base = t0(repo)
    (repo / "tests" / "test_new.py").write_text(FAILING_TEST)
    s = snap(repo, base)
    assert isinstance(s, Snapshot)
    assert "tests/test_new.py" in files(repo, s.commit)
    assert s.parent == base
    assert git(repo, "rev-parse", "refs/delivery/red/t/a/1") == s.commit


def test_tracked_modification_and_untracked_test_both_captured(repo):
    base = t0(repo)
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return -1\n")
    (repo / "tests" / "test_new.py").write_text(FAILING_TEST)
    s = snap(repo, base)
    assert isinstance(s, Snapshot)
    assert set(s.included) == {"src/app.py", "tests/test_new.py"}
    assert git(repo, "show", f"{s.commit}:src/app.py") == "def add(a, b):\n    return -1"


def test_staged_then_modified_file_uses_worktree_version(repo):
    base = t0(repo)
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return 1  # staged\n")
    git(repo, "add", "src/app.py")
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return 2  # worktree\n")
    s = snap(repo, base)
    assert isinstance(s, Snapshot)
    assert "worktree" in git(repo, "show", f"{s.commit}:src/app.py")


def test_staged_excluded_file_is_omitted_and_never_reaches_controller(repo, tmp_path):
    base = t0(repo)
    (repo / ".env.fake").write_text("SECRET=fake\n")
    git(repo, "add", ".env.fake")
    (repo / "tests" / "test_new.py").write_text(FAILING_TEST)
    s = snap(repo, base)
    assert isinstance(s, Snapshot)
    assert ".env.fake" not in files(repo, s.commit)
    assert ".env.fake" in s.omitted_excluded
    ctl = tmp_path / "ctl.git"
    git(tmp_path, "init", "-q", "--bare", str(ctl))
    git(repo, "push", "-q", str(ctl), f"{s.ref}:{s.ref}")
    blob = git(repo, "hash-object", ".env.fake")
    probe = subprocess.run(["git", "cat-file", "-e", blob], cwd=ctl, capture_output=True, check=False)
    assert probe.returncode != 0


def test_staged_out_of_scope_file_refuses_without_ref_or_test_run(repo):
    base = t0(repo)
    (repo / "outside.txt").write_text("x\n")
    git(repo, "add", "outside.txt")
    marker = repo.parent / "ran"
    ev = run_evidence("red", "t", "a", [sys.executable, "-c", f"open({str(marker)!r}, 'w')"], str(repo), base,
                      SCOPE, EXCL)
    assert ev.status == "snapshot_refused"
    assert ev.refusal is not None and ("scope_violation", "outside.txt") in ev.refusal.reasons
    assert not marker.exists()
    assert git(repo, "for-each-ref", "refs/delivery") == ""


def test_baseline_tracked_excluded_file_modified_is_refused(repo):
    (repo / ".env.example").write_text("EXAMPLE=1\n")
    git(repo, "add", "-f", ".env.example")
    git(repo, "commit", "-qm", "example")
    base = t0(repo)
    (repo / ".env.example").write_text("EXAMPLE=2\n")
    s = snap(repo, base)
    assert isinstance(s, Refusal)
    assert ("excluded_tracked_modified", ".env.example") in s.reasons


def test_baseline_tracked_excluded_file_unmodified_is_kept(repo):
    (repo / ".env.example").write_text("EXAMPLE=1\n")
    git(repo, "add", "-f", ".env.example")
    git(repo, "commit", "-qm", "example")
    base = t0(repo)
    (repo / "tests" / "test_new.py").write_text(FAILING_TEST)
    s = snap(repo, base)
    assert isinstance(s, Snapshot)
    assert ".env.example" in files(repo, s.commit)


def test_committed_out_of_scope_file_since_t0_is_refused(repo):
    base = t0(repo)
    (repo / "outside.txt").write_text("x\n")
    git(repo, "add", "outside.txt")
    git(repo, "commit", "-qm", "oops")
    s = snap(repo, base)
    assert isinstance(s, Refusal)
    assert ("committed_scope_violation", "outside.txt") in s.reasons


def test_red_run_records_failing_ids_and_replays_from_snapshot(repo, tmp_path):
    base = t0(repo)
    (repo / "tests" / "test_new.py").write_text(FAILING_TEST)
    ev = run_evidence("red", "t", "a", PYTEST, str(repo), base, SCOPE, EXCL)
    assert isinstance(ev, Evidence)
    assert ev.status == "test_failed"
    assert ev.failing_ids == ("tests.test_new::test_add",)
    assert ev.snapshot is not None
    assert ev.digests["stdout"] == hashlib.sha256(ev.stdout).hexdigest()
    replay = tmp_path / "replay"
    git(repo, "worktree", "add", "-q", "--detach", str(replay), ev.snapshot.commit)
    again = run_evidence("replay_check", "t", "a", PYTEST, str(replay), ev.snapshot.commit, SCOPE, EXCL)
    assert again.failing_ids == ev.failing_ids


def test_syntax_error_is_collection_error_not_behavior_red(repo):
    base = t0(repo)
    (repo / "tests" / "test_new.py").write_text("def test_x(:\n    pass\n")
    ev = run_evidence("red", "t", "a", PYTEST, str(repo), base, SCOPE, EXCL)
    assert ev.status == "collection_error"
    assert ev.failing_ids == ()


def test_allowed_file_changed_during_run_is_drift(repo):
    base = t0(repo)
    (repo / "tests" / "test_new.py").write_text(FAILING_TEST)
    mutate = [sys.executable, "-c",
              "open('src/app.py','a').write('# mutated\\n'); raise SystemExit(1)"]
    ev = run_evidence("red", "t", "a", mutate, str(repo), base, SCOPE, EXCL)
    assert ev.status == "snapshot_drift"


def test_env_does_not_leak_unlisted_variables(repo, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    ev = run_evidence("red", "t", "a", PYTEST, str(repo), t0(repo), SCOPE, EXCL)
    assert "must-not-leak" not in repr(ev.digests)
    assert os.environ["GH_TOKEN"] == "must-not-leak"


def test_green_run_records_passing_ids_for_red_lineage(repo):
    base = t0(repo)
    (repo / "tests" / "test_new.py").write_text("def test_ok():\n    assert True\n\n\ndef test_ok2():\n    assert 1\n")
    ev = run_evidence("green", "t", "a", PYTEST, str(repo), base, SCOPE, EXCL)
    assert ev.status == "passed"
    assert ev.passing_ids == ("tests.test_new::test_ok", "tests.test_new::test_ok2")
