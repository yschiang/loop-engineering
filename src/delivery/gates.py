"""Deterministic gate evaluators (design §6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

IsAncestor = Callable[[str, str], bool]


RUNNER = "delivery-runner"
CONTROLLER_RUNNER = "controller-runner"
# Worst status wins when combining tasks and green.
_ORDER = ("passed", "pending", "unknown", "stale", "missing", "failed")


def _worst(statuses: list[str]) -> str:
    return max(statuses, key=_ORDER.index) if statuses else "passed"


def _red_problems(e: dict[str, Any], green_ids: set[str], head: str, is_ancestor: IsAncestor) -> list[str]:
    problems: list[str] = []
    if e.get("producer", {}).get("tool") != RUNNER:
        problems.append(f"producer {e.get('producer')} is not {RUNNER}")
    if not e.get("digest_ok"):
        problems.append("digest mismatch between record and raw output")
    if e.get("status") != "test_failed":
        problems.append(f"red status {e.get('status')} is not a behavior failure (collection_error/refusal/pass)")
    snap = e.get("snapshot") or {}
    if not snap.get("parent") or not is_ancestor(snap["parent"], head):
        problems.append(f"lineage: red parent {snap.get('parent')} is not an ancestor of head {head}")
    missing = [t for t in e.get("failing_ids", []) if t not in green_ids]
    if missing:
        problems.append(f"red tests not passing at head: {missing}")
    return problems


def _task_g1(t: dict[str, Any], green_ids: set[str], head: str, is_ancestor: IsAncestor) -> dict[str, Any]:
    if t["change_class"] == "na_requested":
        na = t.get("na")
        if na is None:
            return {"status": "failed", "reasons": ["N/A self-declared without independent eligibility"]}
        if na["status"] == "pending":
            return {"status": "pending", "reasons": ["N/A eligibility review pending"]}
        if na["status"] != "accepted":
            return {"status": "failed", "reasons": [f"N/A rejected: {na.get('reason', '')}"]}
        if na.get("diff_digest") != t.get("diff_digest"):
            return {"status": "failed", "reasons": ["N/A accepted for a different diff"]}
        return {"status": "passed", "reasons": [], "na": "accepted"}
    originals = [e for e in t.get("red", []) if e.get("kind") == "red"
                 or e.get("red_source") == "replay_by_decision"]
    if not originals:
        return {"status": "missing", "reasons": ["no historical Red (replays are not original test-first evidence)"]}
    reasons: list[str] = []
    for e in originals:
        problems = _red_problems(e, green_ids, head, is_ancestor)
        if problems:
            reasons += problems
            continue
        replay = e.get("replay")
        if e.get("red_source") != "replay_by_decision" and (
                replay is None or replay.get("status") != "test_failed"
                or sorted(replay.get("failing_ids", [])) != sorted(e["failing_ids"])):
            return {"status": "unknown", "reasons": ["red could not be reproduced from its snapshot"]}
        snap = e["snapshot"]
        return {"status": "passed", "reasons": [], "method_changed": bool(e.get("method_changed")),
                "red_source": e.get("red_source", "original"),
                "lineage": {"red_snapshot": snap["commit"], "red_parent": snap["parent"], "head": head}}
    return {"status": "failed", "reasons": reasons}


def evaluate_g1(tasks: list[dict[str, Any]], green: dict[str, Any] | None, head: str,
                is_ancestor: IsAncestor) -> dict[str, Any]:
    """Deterministic G1. method_changed is carried for the new-contract G2, never a G1 blocker (N-V3-01)."""
    reasons: list[str] = []
    if green is None:
        return {"status": "missing", "reasons": ["no controller Green at head"], "tasks": {}}
    if green.get("producer", {}).get("tool") != CONTROLLER_RUNNER:
        return {"status": "failed", "reasons": ["Green not produced by the controller at head"], "tasks": {}}
    if green["head"] != head:
        return {"status": "stale", "reasons": [f"Green is for {green['head']}, head is {head}"], "tasks": {}}
    statuses: list[str] = []
    if green["status"] != "passed":
        statuses.append("failed")
        reasons.append(f"integration regression at head: {green.get('failing_ids', [])}")
    green_ids = set(green.get("passing_ids", []))
    per_task = {t["task_id"]: _task_g1(t, green_ids, head, is_ancestor) for t in tasks}
    for tid, r in per_task.items():
        statuses.append(r["status"])
        reasons += [f"{tid}: {x}" for x in r["reasons"]]
    return {"status": _worst(statuses), "reasons": reasons, "tasks": per_task}


def evaluate_g2(review: dict[str, Any] | None, current_vs: dict[str, Any], current_key: str,
                profile: dict[str, Any], isolation: dict[str, Any] | None, implementer_sessions: set[str],
                open_blocking_findings: list[str]) -> dict[str, Any]:
    raise NotImplementedError
