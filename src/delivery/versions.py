"""Bindings/observations, VersionSet, dependency matrix and assessment derivation (design §5, DR-02/03/10)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

GATES = ("g1", "g2", "g3")
ROLES = ("project_spec", "feature_spec", "issue_body", "design", "plan", "validation", "policy")
KNOWN_SKILLS = ("superpowers:test-driven-development", "openspec-apply-change")

Evaluator = Callable[[dict[str, Any], dict[str, Any]], tuple[str, list[str]]]


class DecisionRejected(ValueError):
    pass


ALLOWED_ADOPT_KEYS = frozenset({"kind", "role", "actor", "source", "reason", "decision_id", "created_at"})
_SCALARS = ("repo_id", "pr_number", "head_sha", "base_ref", "base_tip", "merge_base", "controller_version")
# Precedence when several changed fields hit one gate: the strongest rule wins.
_STRENGTH = {"R-unaffected": 0, "R-reevaluate": 1, "R-base": 2, "R-reobserve": 3, "stale": 4}


def version_key(vs: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(vs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def matrix_rows() -> dict[str, dict[str, str]]:
    """Every VersionSet field x gate. G3 is re-observed on every change (never carried)."""
    rows: dict[str, dict[str, str]] = {
        "repo_id": {"g1": "stale", "g2": "stale", "g3": "stale"},
        "pr_number": {"g1": "R-unaffected", "g2": "stale", "g3": "R-reobserve"},
        "head_sha": {"g1": "stale", "g2": "stale", "g3": "R-reobserve"},
        "controller_version": {"g1": "R-reevaluate", "g2": "R-reevaluate", "g3": "R-reobserve"},
    }
    for f in ("base_ref", "base_tip", "merge_base"):
        rows[f] = {"g1": "R-base", "g2": "stale", "g3": "R-reobserve"}
    for role in ROLES:
        g2 = "R-reevaluate" if role == "policy" else "stale"
        rows[f"bindings.{role}"] = {"g1": "R-reevaluate", "g2": g2, "g3": "R-reobserve"}
    for name in KNOWN_SKILLS:
        rows[f"skills.{name}"] = {"g1": "R-reevaluate", "g2": "stale", "g3": "R-reobserve"}
    return rows


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def observe_binding(state: dict[str, Any], role: str, locator: str, content: bytes, now: str) -> str:
    """Record a read. Same bytes only refresh last_observed_at; different bytes become a candidate."""
    digest = _digest(content)
    current = state["bindings"].get(role)
    if current is None:
        state["bindings"][role] = {"locator": locator, "content_digest": digest, "adopted_at": now,
                                   "adopted_via": "intake", "last_observed_at": now}
        return "adopted"
    if current["content_digest"] == digest:
        current["last_observed_at"] = now
        return "unchanged"
    state["candidates"][role] = {"locator": locator, "content_digest": digest, "observed_at": now}
    state["phase"] = "awaiting_approval"
    return "candidate"


def adopt_binding(state: dict[str, Any], decision: dict[str, Any]) -> None:
    extra = set(decision) - ALLOWED_ADOPT_KEYS
    if decision.get("kind") != "adopt_binding" or extra:
        raise DecisionRejected(f"adopt_binding decision rejected; unexpected keys {sorted(extra)}")
    if not decision.get("actor") or not decision.get("source"):
        raise DecisionRejected("adopt_binding needs actor and source")
    cand = state["candidates"].pop(decision["role"])
    state["bindings"][decision["role"]] = {"locator": cand["locator"], "content_digest": cand["content_digest"],
                                           "adopted_at": decision.get("created_at", cand["observed_at"]),
                                           "adopted_via": decision.get("decision_id", "decision"),
                                           "last_observed_at": cand["observed_at"]}


def version_set(state: dict[str, Any]) -> dict[str, Any]:
    return {**{k: state["facts"][k] for k in _SCALARS if k != "controller_version"},
            "bindings": {r: b["content_digest"] for r, b in state["bindings"].items()},
            "skills": dict(state["skills"]), "controller_version": state["controller_version"]}


def _changed(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if isinstance(a, dict) or isinstance(b, dict):
            a, b = a or {}, b or {}
            fields += [f"{key}.{k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        elif a != b:
            fields.append(key)
    return fields


def derive(assessment: dict[str, Any], old_vs: dict[str, Any], new_vs: dict[str, Any],
           reevaluate: Evaluator | None = None, base_recheck: dict[str, Any] | None = None) -> dict[str, Any]:
    """New assessment for new_vs. Original evidence identities are never rewritten."""
    fields = _changed(old_vs, new_vs)
    if not fields:
        return assessment
    gate = assessment["gate"]
    rows = matrix_rows()
    rules = {rows.get(f, {}).get(gate, "stale") for f in fields}  # unknown field or skill: dependency
    rule = max(rules, key=lambda r: _STRENGTH[r])
    out: dict[str, Any] = {"gate": gate, "version_key": version_key(new_vs), "evidence": list(assessment["evidence"]),
                           "reasons": [], "derived": {"from": assessment["version_key"], "rule": rule,
                                                      "changed_fields": fields}}
    status = assessment["status"]
    if rule == "stale":
        status = "stale"
    elif rule == "R-reobserve":
        status, out["evidence"] = "pending", []
    else:
        if "R-base" in rules:
            if base_recheck is None:
                status = "stale"
                out["reasons"].append("base changed: base_recheck evidence required")
            else:
                status = base_recheck["status"]
                out["evidence"] += base_recheck.get("evidence", [])
                out["reasons"] += [base_recheck["reason"]] if "reason" in base_recheck else []
        if "R-reevaluate" in rules and status not in ("stale", "failed"):
            if reevaluate is None:
                status = "stale"
            else:
                status, reasons = reevaluate(assessment, new_vs)
                out["reasons"] += reasons
            if any(f.startswith("skills.") for f in fields):
                out["derived"]["method_changed"] = True
    out["status"] = status
    return out
