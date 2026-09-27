"""Correction batches, round cap, one dispute review and recurrence (design §7, D13/D25)."""

from __future__ import annotations

from typing import Any

MAX_ROUNDS = 3


MAX_FAILED_RECHECKS = 2  # D40-approved recurrence default
_TERMINAL = frozenset({"passed", "failed", "unknown", "stale", "missing"})


def _block(state: dict[str, Any], kind: str, **detail: Any) -> None:
    state["blockers"].append({"kind": kind, **detail})


def ready_for_batch(g2: dict[str, Any], g3: dict[str, Any]) -> bool:
    """Collect the same-version review and CI before fixing, so work is never dispatched twice."""
    return g2["status"] in _TERMINAL and g3["status"] in _TERMINAL


def dispatch_batch(state: dict[str, Any], version_key: str, finding_ids: list[str],
                   ci_failures: list[str], base_conflict: bool = False) -> dict[str, Any]:
    findings = state["registry"]["findings"]
    for fid in finding_ids:
        f = findings[fid]
        if f.get("failed_rechecks", 0) >= MAX_FAILED_RECHECKS or f.get("reopen_count", 0) >= 1:
            _block(state, "recurrence", finding_id=fid, failed_rechecks=f.get("failed_rechecks", 0),
                   reopen_count=f.get("reopen_count", 0),
                   rounds_left=MAX_ROUNDS - state["budget"]["correction_rounds_used"])
            return {"dispatched": False, "batch": None}
    if state["budget"]["correction_rounds_used"] >= MAX_ROUNDS:
        _block(state, "correction_rounds_exhausted", open_findings=finding_ids)
        return {"dispatched": False, "batch": None}
    batch = {"batch_id": f"b{len(state['batches']) + 1}", "version_key": version_key,
             "items": {"findings": list(finding_ids), "ci": list(ci_failures), "base_conflict": base_conflict}}
    state["batches"].append(batch)
    state["budget"]["correction_rounds_used"] += 1  # counted when the batch dispatch is registered
    return {"dispatched": True, "batch": batch}


def check_result(batch: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """IDs lacking a fix_submitted/disputed response; a non-empty list means the result is incomplete."""
    responses = result.get("responses", {})
    return [fid for fid in batch["items"]["findings"]
            if responses.get(fid, {}).get("kind") not in ("fix_submitted", "disputed")]


def record_recheck(state: dict[str, Any], fid: str, still_open: bool, batch_id: str, result_id: str) -> None:
    f = state["registry"]["findings"][fid]
    seen = f.setdefault("recheck_keys", [])
    key = f"{batch_id}:{result_id}"
    if key in seen:  # duplicate notification or resent result
        return
    seen.append(key)
    if still_open:
        f["failed_rechecks"] = f.get("failed_rechecks", 0) + 1


def reopen(state: dict[str, Any], fid: str, reviewer_basis: str) -> None:
    if not reviewer_basis:
        raise ValueError("reopen needs the Reviewer's basis for semantic identity")
    f = state["registry"]["findings"][fid]
    f["status"] = "open"
    f["reopen_count"] = f.get("reopen_count", 0) + 1
    f.setdefault("lineage", []).append({"reopened": True, "basis": reviewer_basis})


def request_dispute_review(state: dict[str, Any], fid: str, counter_evidence: str,
                           new_head: bool) -> dict[str, Any]:
    d = state["disputes"].setdefault(fid, {"reviews_used": 0, "counter_evidence": []})
    if d["reviews_used"] >= 1:
        _block(state, "dispute_review_exhausted", finding_id=fid)
        return {"next": "blocked"}
    d["counter_evidence"].append(counter_evidence)
    d["reviews_used"] = 1
    state["registry"]["findings"][fid]["status"] = "disputed"
    return {"next": "validating" if new_head else "dispute_review"}


def settle_dispute(state: dict[str, Any], fid: str, reviewer_accepts: bool) -> dict[str, Any]:
    f = state["registry"]["findings"][fid]
    if reviewer_accepts:
        f["status"] = "resolved"
    else:
        f["status"] = "dispute_upheld"
        _block(state, "dispute_upheld", finding_id=fid)
    return state
