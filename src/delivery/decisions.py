"""Human decisions and acceptance bound to versions (design §4, D03/D11/D19)."""

from __future__ import annotations

from typing import Any

from delivery.correction import MAX_ROUNDS


class DecisionInvalid(ValueError):
    pass


KINDS = frozenset({"approve_plan", "revise", "scope_change", "accept", "return", "budget_extension",
                   "abandon_run", "unblock", "policy_change", "adopt_binding", "resolve_finding", "waive_finding"})
REQUIRED = ("decision_id", "kind", "actor", "actor_kind", "source", "reason", "created_at", "subject")


def _validate(decision: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED if not decision.get(k) and k != "subject"]
    if missing or "subject" not in decision:
        raise DecisionInvalid(f"decision missing {missing or ['subject']}")
    if decision["kind"] not in KINDS:
        raise DecisionInvalid(f"{decision['kind']!r} is not a decision (gates are derived from evidence)")
    if decision["actor_kind"] != "human":
        raise DecisionInvalid("only an explicit human decision counts; silence, timeouts and agents do not")


def _return(state: dict[str, Any], decision: dict[str, Any]) -> None:
    sub = decision["subject"]
    source_id = f"human:{sub['feedback_id']}"
    if any(f.get("source_id") == source_id for f in state["registry"]["findings"].values()):
        return  # the same feedback resent: already recorded against its version
    if state.get("current_pass") is None or sub.get("version_key") != state["current_pass"]["version_key"]:
        raise DecisionInvalid("return must name the delivered version")
    if sub["category"] != "ac_defect":
        state["phase"] = "blocked"
        state["blockers"].append({"kind": "human_return", "category": sub["category"],
                                  "route": "project_lead_and_user", "decision_id": decision["decision_id"]})
        return
    reg = state["registry"]
    reg["seq"] += 1
    fid = f"F-{reg['seq']:04d}"
    reg["findings"][fid] = {"id": fid, "source": "human_acceptance", "source_id": source_id,
                            "blocking": True, "status": "open", "problem": sub.get("difference"),
                            "basis": sub.get("ac_id"), "version_key": sub["version_key"],
                            "actor": decision["actor"], "created_at": decision["created_at"],
                            "fix_commits": [], "rechecks": [], "events": [], "history": [], "closure": None}
    state["current_pass"] = None
    if state["budget"]["correction_rounds_used"] >= MAX_ROUNDS:
        state["phase"] = "blocked"
        state["blockers"].append({"kind": "correction_rounds_exhausted", "decision_id": decision["decision_id"]})
    else:
        state["phase"] = "correcting"


def _adopt_binding(state: dict[str, Any], decision: dict[str, Any]) -> None:
    from delivery.controller import reassess

    role = decision["subject"].get("role")
    cand = state.get("candidates", {}).get(role)
    if cand is None:
        raise DecisionInvalid(f"no candidate binding for role {role!r} to adopt")
    new_vs = {**state["versions"], "bindings": {**state["versions"]["bindings"], role: cand["content_digest"]}}
    del state["candidates"][role]
    reassess(state, new_vs)
    if not state["candidates"]:
        state["phase"] = "awaiting_approval"
        state["contract_adopted"] = True


def apply_decision(state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    _validate(decision)
    kind, sub = decision["kind"], decision["subject"]
    if kind == "approve_plan":
        if sub.get("plan_version") != state["plan_version"]:
            raise DecisionInvalid("approval must name the current plan version")
        state["approval"] = {"decision_id": decision["decision_id"], "plan_version": sub["plan_version"]}
        state["phase"] = "implementing"
    elif kind == "scope_change":
        state["pending_scope"].append(sub)
        state["phase"] = "awaiting_approval"
    elif kind == "accept":
        if state.get("current_pass") is None or sub.get("version_key") != state["current_pass"]["version_key"]:
            raise DecisionInvalid("acceptance must name the version that holds the current Pass")
        state["acceptance"]["history"].append({"status": "accepted", "version_key": sub["version_key"],
                                               "decision_id": decision["decision_id"]})
    elif kind == "return":
        _return(state, decision)
    elif kind == "adopt_binding":
        _adopt_binding(state, decision)
    elif kind == "budget_extension":
        state["budget"]["extensions"].append({"decision_id": decision["decision_id"], "seconds": sub["seconds"]})
    state.setdefault("decisions", []).append(decision)
    return state


def may_dispatch_implementation(state: dict[str, Any]) -> bool:
    approval = state.get("approval")
    return approval is not None and approval["plan_version"] == state["plan_version"]


def acceptance_for(state: dict[str, Any], version_key: str) -> str:
    accepted = any(h["status"] == "accepted" and h["version_key"] == version_key
                   for h in state["acceptance"]["history"])
    return "accepted" if accepted else "pending"
