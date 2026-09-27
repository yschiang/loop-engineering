"""Finding registry: stable IDs, blocking rules and closure authority (design §7, D09/D12/D24)."""

from __future__ import annotations

from typing import Any


class ClosureRejected(ValueError):
    pass


BLOCKING_CATEGORIES = frozenset({"spec_ac", "correctness_security", "missing_verification"})  # D12
_FIELDS = ("category", "severity", "location", "problem", "basis", "expected")


def import_review(registry: dict[str, Any], review: dict[str, Any], version_key: str) -> list[str]:
    """Reviewer-asserted `matches` keeps an ID; the controller never merges by location or text."""
    ids: list[str] = []
    for f in review["findings"]:
        fid = f.get("matches")
        if fid not in registry["findings"]:
            registry["seq"] += 1
            fid = f"F-{registry['seq']:04d}"
            registry["findings"][fid] = {"id": fid, "source": review.get("source", "reviewer"), "status": "open",
                                         "fix_commits": [], "rechecks": [], "events": [], "history": [],
                                         "closure": None}
        entry = registry["findings"][fid]
        entry.update({k: f.get(k) for k in _FIELDS})
        entry["blocking"] = f["category"] in BLOCKING_CATEGORIES  # severity only orders work
        entry["history"].append({"result_id": review["result_id"], "version_key": version_key,
                                 "location": f.get("location")})
        ids.append(fid)
    return ids


def submit_fix(registry: dict[str, Any], fid: str, commit: str, evidence: list[str]) -> None:
    entry = registry["findings"][fid]
    entry["fix_commits"].append({"commit": commit, "evidence": evidence})
    entry["status"] = "fix_submitted"


def record_external(registry: dict[str, Any], fid: str, event: dict[str, Any]) -> None:
    """GitHub threads, approvals and notifications are evidence only; they never change status."""
    registry["findings"][fid]["events"].append(event)


def close(registry: dict[str, Any], fid: str, closure: dict[str, Any], current_key: str) -> None:
    entry = registry["findings"][fid]
    kind = closure.get("actor_kind")
    if kind == "reviewer":
        if closure.get("version_key") != current_key or not closure.get("result_id") or not closure.get("evidence"):
            raise ClosureRejected("reviewer closure must cite a current-version result and evidence")
        entry.update(status="resolved", closure=dict(closure))
        return
    if kind == "human":
        d = closure.get("decision") or {}
        if (d.get("kind") not in ("resolve_finding", "waive_finding") or d.get("finding_id") != fid
                or d.get("version_key") != current_key or not d.get("actor") or not d.get("reason")):
            raise ClosureRejected("human closure needs a decision naming this finding and the current version")
        entry.update(status="resolved" if d["kind"] == "resolve_finding" else "waived", closure=dict(closure))
        return
    raise ClosureRejected(f"{kind!r} cannot close findings (D09)")


def open_blocking(registry: dict[str, Any]) -> list[str]:
    return [fid for fid, f in registry["findings"].items()
            if f["blocking"] and f["status"] not in ("resolved", "waived")]
