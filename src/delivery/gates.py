"""Deterministic gate evaluators (design §6)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

IsAncestor = Callable[[str, str], bool]


GATE_NAMES = ("g1", "g2", "g3")
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
    """G2 passes only for a controller-dispatched, verified-isolated review of the current contract."""
    out: dict[str, Any] = {"gate": "g2", "version_key": current_key, "reasons": [],
                           "blocks_feature": False, "opens_correction_round": False}

    def unknown(reason: str) -> dict[str, Any]:
        out["reasons"].append(reason)
        return {**out, "status": "unknown"}

    if review is None:
        return {**out, "status": "missing", "reasons": ["no review for the current version"]}
    if review.get("dispatched_by") != "controller" or review.get("role") != "reviewer":
        return unknown("not a controller-dispatched Reviewer assignment")
    if review["session_id"] in implementer_sessions or review.get("parent_session_id") in implementer_sessions:
        return unknown("reviewer session is an implementer session or its child")
    if review["version_key"] != current_key:
        return {**out, "status": "stale", "reasons": [f"review is for {review['version_key']}"]}
    if review.get("requested_model") != profile["model"] or review.get("actual_model") != profile["model"]:
        return unknown(f"model mismatch: requested {review.get('requested_model')}, actual "
                       f"{review.get('actual_model')}, approved {profile['model']}")
    if not isolation or isolation.get("status") != "verified":
        return unknown("reviewer isolation not verified by the negative-probe suite")
    if isolation.get("profile_digest") != review.get("receipt_profile_digest"):
        return unknown("dispatch receipt sandbox profile does not match the verified isolation report")
    expected = {k: current_vs.get(k) for k in ("head_sha", "base_tip", "bindings", "skills")}
    if review.get("read_contract") != expected:
        return unknown("review did not read the current contract digests")
    if review["verdict"] == "blocked":
        out["blocks_feature"] = True
        return unknown("reviewer could not decide (verdict blocked)")
    if review["verdict"] != "clean" or open_blocking_findings:
        return {**out, "status": "failed",
                "reasons": [f"verdict {review['verdict']}; open blocking findings {open_blocking_findings}"]}
    return {**out, "status": "passed"}


def evaluate_g3(policy: dict[str, Any], repo_rules: set[str] | None, head: str, base_tip: str,
                merge: dict[str, Any] | None, checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Only completed success (or an explicitly allowed conclusion) on the right SHA and app passes."""
    required = policy.get("required", [])
    if not required:
        return {"gate": "g3", "status": "failed", "reasons": ["required check set is empty"]}
    if repo_rules is None:
        return {"gate": "g3", "status": "unknown", "reasons": ["repository required-check rules unreadable"]}
    names = {r["name"] for r in required}
    if names != repo_rules:
        return {"gate": "g3", "status": "failed",
                "reasons": [f"policy mismatch: workflow {sorted(names)} vs repo rules {sorted(repo_rules)}"]}
    statuses: list[str] = []
    reasons: list[str] = []
    out: dict[str, Any] = {"gate": "g3"}
    for req in required:
        name, app = req["name"], req["app"]
        sha = head
        if req.get("source", "head") == "merge":
            if merge is None:
                statuses.append("unknown")
                reasons.append(f"{name}: merge snapshot not computed yet")
                continue
            if merge["parents"] != [base_tip, head]:
                statuses.append("stale")
                reasons.append(f"{name}: merge snapshot {merge['sha']} is for parents {merge['parents']}")
                continue
            sha = merge["sha"]
            out["merge_mapping"] = merge
        same = [c for c in checks if c["name"] == name and c["app"] == app]
        here = [c for c in same if c["head_sha"] == sha]
        if not here:
            statuses.append("stale" if same else "missing")
            reasons.append(f"{name}: {'stale (only other SHAs)' if same else 'missing'}")
            continue
        latest = max(here, key=lambda c: (c["started_at"], c["id"]))
        concl = latest.get("conclusion")
        allowed = {c for a in policy.get("allow_non_success", []) if a["name"] == name for c in a["conclusions"]}
        if latest["status"] != "completed":
            statuses.append("pending")
            reasons.append(f"{name}: pending ({latest['status']})")
        elif concl == "success" or concl in allowed:
            statuses.append("passed")
        elif concl in ("cancelled", "timed_out", "failure", "action_required", "startup_failure", "skipped",
                       "neutral", "stale"):
            statuses.append("failed")
            reasons.append(f"{name}: conclusion {concl}")
        else:
            statuses.append("unknown")
            reasons.append(f"{name}: unrecognised conclusion {concl}")
    return {**out, "status": _worst(statuses), "reasons": reasons}


def decide_pass(state: dict[str, Any], current_key: str, open_blocking: list[str],
                reread: Callable[[], str], now: str) -> dict[str, Any]:
    """Record Pass only from gate assessments; task results and notifications never count."""
    gates = state["gates"]
    ready = all(gates[g]["status"] == "passed" and gates[g]["version_key"] == current_key for g in GATE_NAMES)
    if not ready or open_blocking:
        return state
    observed = reread()
    if observed != current_key:
        state["next_action"] = {"kind": "reconcile",
                                "detail": f"re-read before Pass saw {observed}, expected {current_key}"}
        return state
    record = {"version_key": current_key, "observed_at": now,
              "gates": {g: gates[g]["version_key"] for g in GATE_NAMES}}
    state["current_pass"] = record
    state["pass_history"].append(dict(record))
    state["phase"] = "ready_for_acceptance"
    return state


def observe_new_version(state: dict[str, Any], new_key: str, now: str) -> dict[str, Any]:
    """A new version invalidates the current Pass; the historical Pass stays with its version."""
    current = state.get("current_pass")
    if current is not None and current["version_key"] != new_key:
        state["pass_history"][-1]["invalidated_at"] = now
        state["current_pass"] = None
        state["phase"] = "validating"
    return state
