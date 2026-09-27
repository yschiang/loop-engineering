"""Single-writer integration: fetch attempt, verify, CAS fast-forward (design §9.2, DR-05)."""

from __future__ import annotations

import subprocess
from typing import Any


def _git(cwd: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _in_scope(path: str, scope: list[str]) -> bool:
    return any(path == s or path.startswith(s.rstrip("/") + "/") for s in scope)


def integrate(ctl_repo: str, state: dict[str, Any], task_id: str, attempt_id: str, clone_path: str,
              t0: str, scope: list[str], branch: str) -> dict[str, Any]:
    """Idempotent: re-running after any crash converges by reading the branch ref (T0 redo, A done)."""
    task = next((t for t in state["tasks"] if t["task_id"] == task_id), None)  # design §4: ordered task list
    if task is None or task.get("lease") != attempt_id:
        return {"status": "rejected", "reason": f"attempt {attempt_id} does not hold the task lease (fenced)"}
    attempt_ref = f"refs/delivery/attempts/{attempt_id}"
    _git(ctl_repo, "fetch", "-q", "--no-tags", clone_path, f"+HEAD:{attempt_ref}")
    a = _git(ctl_repo, "rev-parse", attempt_ref).stdout.strip()
    if _git(ctl_repo, "merge-base", "--is-ancestor", t0, a, check=False).returncode != 0:
        return {"status": "rejected", "reason": f"attempt head {a} does not descend from T0 {t0}"}
    outside = [p for p in _git(ctl_repo, "diff", "--name-only", t0, a).stdout.split() if not _in_scope(p, scope)]
    if outside:
        return {"status": "rejected", "reason": f"changes outside scope: {outside}"}
    ref = f"refs/heads/{branch}"
    current = _git(ctl_repo, "rev-parse", ref).stdout.strip()
    already = current == a
    if not already:
        if current != t0:
            state["blockers"].append({"kind": "integration_conflict", "task_id": task_id, "expected": t0,
                                      "found": current, "attempt_head": a})
            return {"status": "blocked", "reason": f"{ref} is {current}, expected {t0} or {a}"}
        _git(ctl_repo, "update-ref", ref, a, t0)  # compare-and-swap: fails if the ref moved meanwhile
    log = state["integration"]["log"]
    if not any(e["attempt_id"] == attempt_id for e in log):
        log.append({"task_id": task_id, "attempt_id": attempt_id, "from": t0, "to": a})
    return {"status": "succeeded", "head": a, "already_integrated": already}
