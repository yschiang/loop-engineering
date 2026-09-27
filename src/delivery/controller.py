"""Feature phase routing and dispatch guards (design §3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def route_intake(facts: dict[str, Any]) -> dict[str, Any]:
    """First phase for start/adopt; unsafe or ambiguous inputs block with each gap listed."""
    out: dict[str, Any] = {k: facts[k] for k in ("feature_owner", "controller_run") if k in facts}
    blockers: list[dict[str, Any]] = []
    src = facts["sources"]
    if src["conflicts"] or src["unreadable"]:
        blockers.append({"kind": "source_conflict", "seen": src["conflicts"], "unreadable": src["unreadable"]})
    if not facts["owner_handoff"]:
        blockers.append({"kind": "owner_not_handed_over"})
    blockers += [{"kind": "unknown_writer", "writer": w} for w in facts["unknown_writers"]]
    if facts["kind"] == "adopt":
        if not facts.get("historical_red", True) and facts.get("tasks_done"):
            blockers.append({"kind": "missing_historical_red"})
        if not facts.get("fixed_base", True):
            blockers.append({"kind": "unfixed_base"})
    if blockers:
        return {**out, "phase": "blocked", "blockers": blockers}
    if facts["kind"] == "new" or not facts.get("has_plan"):
        return {**out, "phase": "planning", "blockers": []}
    if not facts.get("d11"):
        return {**out, "phase": "awaiting_approval", "blockers": []}
    if not facts.get("tasks_done"):
        return {**out, "phase": "implementing", "blockers": []}
    return {**out, "phase": "checking" if facts.get("g1_verified") else "validating", "blockers": []}


def authorize_dispatch(state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Only the controller dispatches, and only inside an approved implementer plan (D11, D23)."""
    def no(reason: str) -> dict[str, Any]:
        return {"accepted": False, "reason": reason}

    if request["via"] != "controller":
        return no(f"dispatch requested via {request['via']}; only the controller dispatches")
    approval = state.get("approval")
    if approval is None or approval["plan_version"] != state["plan_version"]:
        return no("no D11 approval for the current plan version")
    if approval.get("plan_producer") != "implementer":
        return no("approved plan must be the implementer's calibrated plan, not a draft")
    if request["requested_by"] == "project_lead":
        auth = request.get("authorization") or {}
        if not auth.get("source") or request["task_id"] not in auth.get("scope", []):
            return no("project lead request lacks a user authorisation covering this task")
    task = state["tasks"].get(request["task_id"])
    if task is None or task["status"] == "blocked":
        return no(f"task {request['task_id']} is not dispatchable")
    if not state["budget_ok"] or not state["deps_ready"]:
        return no("budget or dependencies not satisfied")
    return {"accepted": True, "reason": ""}


def dependency_ready(dep: dict[str, Any], is_ancestor: Callable[[str, str], bool], baseline: str) -> dict[str, Any]:
    """D27: upstream version accepted AND merged AND the merge is in the baseline we build on."""
    if dep["version"] not in dep["accepted_versions"]:
        return {"ready": False, "wait": "upstream version not accepted"}
    if not dep["merged"] or not dep["merge_commit"]:
        return {"ready": False, "wait": "upstream accepted but not merged"}
    if not is_ancestor(dep["merge_commit"], baseline):
        return {"ready": False, "wait": "baseline does not contain the upstream merge"}
    return {"ready": True, "wait": ""}


def mark_cross_feature_impact(state: dict[str, Any], task_ids: list[str], impact: str) -> None:
    for tid in task_ids:
        state["tasks"][tid]["status"] = "blocked"
    state["blockers"].append({"kind": "cross_feature_impact", "tasks": task_ids, "impact": impact,
                              "route": "project_lead_and_user"})


def reassess(state: dict[str, Any], new_vs: dict[str, Any], reevaluate: Any = None,
             base_recheck: dict[str, Any] | None = None) -> dict[str, Any]:
    raise NotImplementedError
