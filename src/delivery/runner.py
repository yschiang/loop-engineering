"""Evidence runner and baseline+overlay Red snapshot (design §6.1 v3)."""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Only these variables reach the evidence record; everything else (tokens included) stays out.
ENV_ALLOWLIST = ("PATH", "PYTHONPATH", "VIRTUAL_ENV", "LANG")


@dataclass(frozen=True)
class Snapshot:
    commit: str
    tree: str
    parent: str
    ref: str
    included: tuple[str, ...]
    omitted_excluded: tuple[str, ...] = ()
    index_only: tuple[str, ...] = ()


@dataclass(frozen=True)
class Refusal:
    reasons: tuple[tuple[str, str], ...]  # (reason, path) - path names only, never content


@dataclass(frozen=True)
class Evidence:
    task_id: str
    attempt_id: str
    kind: str
    argv: tuple[str, ...]
    cwd: str
    status: str  # passed | test_failed | collection_error | snapshot_refused | snapshot_drift
    exit_code: int | None
    started_at: str
    ended_at: str
    stdout: bytes = b""
    stderr: bytes = b""
    failing_ids: tuple[str, ...] = ()
    passing_ids: tuple[str, ...] = ()
    snapshot: Snapshot | None = None
    refusal: Refusal | None = None
    digests: dict[str, str] = field(default_factory=dict)


def _git(cwd: str, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
                          check=True).stdout


def _in_scope(path: str, scope: list[str]) -> bool:
    return any(path == s or path.startswith(s.rstrip("/") + "/") for s in scope)


def _excluded(path: str, excludes: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, e) or fnmatch.fnmatch(os.path.basename(path), e) for e in excludes)


def _changed_paths(cwd: str, env: dict[str, str]) -> list[str]:
    """Worktree paths differing from the (temporary) index, plus untracked non-ignored files."""
    out = _git(cwd, "status", "--porcelain=v2", "-z", "-uall", env=env)
    paths: list[str] = []
    records = iter(out.split("\0"))
    for rec in records:
        if not rec:
            continue
        kind = rec[0]
        if kind == "?":
            paths.append(rec[2:])
        elif kind in "12u":
            if kind == "2":
                next(records, None)  # rename source path
            worktree_state = rec.split(" ", 2)[1][1]
            if kind == "u" or worktree_state != ".":
                fields = {"1": 8, "2": 9, "u": 10}[kind]
                paths.append(rec.split(" ", fields)[fields])
    return paths


def snapshot_worktree(cwd: str, t0: str, scope_paths: list[str], excludes: list[str],
                      ref: str) -> Snapshot | Refusal:
    """Baseline = HEAD tree; overlay = allowed worktree changes. Refuses before writing any object."""
    reasons: list[tuple[str, str]] = []
    for path in _git(cwd, "diff", "--name-only", t0, "HEAD").split("\n"):
        if path and (not _in_scope(path, scope_paths) or _excluded(path, excludes)):
            reasons.append(("committed_scope_violation", path))
    fd, idx = tempfile.mkstemp(prefix="delivery-idx-")
    os.close(fd)
    os.unlink(idx)
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        _git(cwd, "read-tree", "HEAD", env=env)
        tracked = set(_git(cwd, "ls-tree", "-r", "--name-only", "HEAD").split("\n"))
        allowed: list[str] = []
        omitted: list[str] = []
        for path in _changed_paths(cwd, env):
            if _excluded(path, excludes):
                if path in tracked:
                    reasons.append(("excluded_tracked_modified", path))
                else:
                    omitted.append(path)
            elif not _in_scope(path, scope_paths):
                reasons.append(("scope_violation", path))
            else:
                allowed.append(path)
        if reasons:
            return Refusal(tuple(reasons))
        if allowed:
            _git(cwd, "add", "-A", "--", *[":(literal)" + p for p in allowed], env=env)
        staged = {p for p in _git(cwd, "diff-index", "--cached", "--name-only", "HEAD", env=env).split("\n") if p}
        if staged != set(allowed):
            raise RuntimeError(f"snapshot candidate differs from allowed set: {sorted(staged ^ set(allowed))}")
        tree = _git(cwd, "write-tree", env=env).strip()
    finally:
        if os.path.exists(idx):
            os.unlink(idx)
    parent = _git(cwd, "rev-parse", "HEAD").strip()
    commit = _git(cwd, "commit-tree", tree, "-p", parent, "-m", f"delivery red snapshot {ref}").strip()
    _git(cwd, "update-ref", ref, commit)
    index_only = [p for p in _git(cwd, "diff", "--cached", "--name-only", "HEAD").split("\n")
                  if p and p not in allowed]
    return Snapshot(commit, tree, parent, ref, tuple(sorted(allowed)), tuple(sorted(omitted)),
                    tuple(sorted(index_only)))


def _drifted(cwd: str, snap: Snapshot, scope_paths: list[str], excludes: list[str]) -> list[str]:
    """In-scope, non-excluded worktree paths that no longer match the snapshot tree."""
    fd, idx = tempfile.mkstemp(prefix="delivery-idx-")
    os.close(fd)
    os.unlink(idx)
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        _git(cwd, "read-tree", snap.commit, env=env)
        return [p for p in _changed_paths(cwd, env)
                if _in_scope(p, scope_paths) and not _excluded(p, excludes)]
    finally:
        if os.path.exists(idx):
            os.unlink(idx)


def _case_ids(junit: Path) -> tuple[list[str], list[str]]:
    failing: list[str] = []
    passing: list[str] = []
    if junit.exists():
        for case in ET.parse(junit).iter("testcase"):
            cid = f"{case.get('classname', '')}::{case.get('name')}"
            if case.find("failure") is not None:
                failing.append(cid)
            elif case.find("error") is None and case.find("skipped") is None:
                passing.append(cid)
    return sorted(failing), sorted(passing)


def _classify(exit_code: int, junit: Path) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    failing, passing = _case_ids(junit)
    if exit_code == 0:
        return "passed", (), tuple(passing)
    # pytest exit 1 = tests failed; anything else (2 interrupted/collection, 3-5) is not a behavior Red.
    if exit_code == 1 and failing:
        return "test_failed", tuple(failing), tuple(passing)
    return "collection_error", (), ()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def run_evidence(kind: str, task_id: str, attempt_id: str, argv: list[str], cwd: str, t0: str,
                 scope_paths: list[str], excludes: list[str]) -> Evidence:
    ref = f"refs/delivery/{kind}/{task_id}/{attempt_id}/{_now().replace(':', '').replace('+', 'Z')}"
    snap = snapshot_worktree(cwd, t0, scope_paths, excludes, ref)
    started = _now()
    if isinstance(snap, Refusal):
        return Evidence(task_id, attempt_id, kind, tuple(argv), cwd, "snapshot_refused", None, started, _now(),
                        refusal=snap)
    with tempfile.TemporaryDirectory(prefix="delivery-junit-") as tmp:
        junit = Path(tmp) / "junit.xml"
        cmd = [a.replace("{junit}", str(junit)) for a in argv]
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, check=False)
        status, failing, passing = _classify(proc.returncode, junit)
    ended = _now()
    if _drifted(cwd, snap, scope_paths, excludes):
        status, failing, passing = "snapshot_drift", (), ()
    digests = {"stdout": hashlib.sha256(proc.stdout).hexdigest(), "stderr": hashlib.sha256(proc.stderr).hexdigest(),
               "env": hashlib.sha256(repr(sorted((k, os.environ.get(k, "")) for k in ENV_ALLOWLIST))
                                     .encode()).hexdigest()}
    return Evidence(task_id, attempt_id, kind, tuple(argv), cwd, status, proc.returncode, started, ended,
                    proc.stdout, proc.stderr, failing, passing, snap, None, digests)
