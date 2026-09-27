"""Active-time budget, crash unknown intervals and failure routing (design §12, D13)."""

from __future__ import annotations

from typing import Any

ACTIVE_LIMIT_SECONDS = 4 * 3600  # D13


CORRECTION_KINDS = frozenset({"test_failed", "changes_required", "collection_error", "base_conflict"})
INFRA_KINDS = frozenset({"timeout", "transport_error", "service_unavailable", "outcome_unknown"})


def open_activity(budget: dict[str, Any], activity_id: str, kind: str, now: float) -> None:
    budget.setdefault("activities", {})[activity_id] = {"kind": kind, "start": now, "end": None}


def close_activity(budget: dict[str, Any], activity_id: str, now: float) -> None:
    budget["activities"][activity_id]["end"] = now


def on_resume(budget: dict[str, Any], last_persisted_at: float, resume_at: float,
              external_ends: dict[str, float | None]) -> None:
    """Count the crash gap as active unless every open activity has a proven external end."""
    open_ids = [a for a, v in budget.get("activities", {}).items() if v["end"] is None]
    ends = [external_ends.get(a) for a in open_ids]
    gap_end = resume_at
    if open_ids and all(e is not None for e in ends):
        gap_end = min(resume_at, max(e for e in ends if e is not None))
        for a, e in zip(open_ids, ends, strict=True):
            budget["activities"][a]["end"] = e
    elif open_ids:
        for a in open_ids:
            act = budget["activities"][a]
            act["end"] = last_persisted_at
            budget["activities"][f"{a}@resume"] = {"kind": act["kind"], "start": resume_at, "end": None}
    if open_ids and gap_end > last_persisted_at:
        budget.setdefault("unknown_intervals", []).append([last_persisted_at, gap_end])


def active_seconds(budget: dict[str, Any], now: float) -> float:
    spans = [(v["start"], v["end"] if v["end"] is not None else now) for v in budget.get("activities", {}).values()]
    spans += [(s, e) for s, e in budget.get("unknown_intervals", [])]
    total, cur_start, cur_end = 0.0, None, None
    for start, end in sorted(spans):
        if cur_end is None or start > cur_end:
            if cur_end is not None and cur_start is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None and cur_start is not None:
        total += cur_end - cur_start
    return total


def may_dispatch(budget: dict[str, Any], now: float) -> bool:
    extra = float(sum(e["seconds"] for e in budget.get("extensions", [])))
    return active_seconds(budget, now) < ACTIVE_LIMIT_SECONDS + extra


def failure_route(kind: str) -> str:
    """Program/test/review defects are corrections (3-round cap); only transport-level failures are infra."""
    if kind in CORRECTION_KINDS:
        return "correction"
    if kind in INFRA_KINDS:
        return "infra"
    raise ValueError(f"unclassified failure kind {kind!r}")
