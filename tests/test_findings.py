"""Task 2.6: finding identity, blocking classification, closure authority (AC-F01..F04)."""

import pytest

from delivery.findings import (
    ClosureRejected,
    close,
    import_review,
    open_blocking,
    record_external,
    submit_fix,
)

K = "sha256:v1"


def item(**over):
    f = {"category": "spec_ac", "location": "src/app.py:10", "problem": "AC-G06 red not kept",
         "basis": "delivery-gates GAT-03", "expected": "snapshot keeps red", "severity": "high"}
    f.update(over)
    return f


def reg():
    return {"seq": 0, "findings": {}}


def test_ac_defect_blocks_and_naming_preference_does_not_even_if_marked_high():
    r = reg()
    ids = import_review(r, {"result_id": "rv1", "findings": [
        item(), item(category="preference", problem="rename helper", severity="high", blocking=True)]}, K)
    assert ids == ["F-0001", "F-0002"]
    assert r["findings"]["F-0001"]["blocking"] is True
    assert r["findings"]["F-0002"]["blocking"] is False
    assert r["findings"]["F-0001"]["basis"] == "delivery-gates GAT-03"
    assert open_blocking(r) == ["F-0001"]


def test_reviewer_match_keeps_id_across_moves_and_similar_text_is_not_merged():
    r = reg()
    import_review(r, {"result_id": "rv1", "findings": [item()]}, K)
    ids = import_review(r, {"result_id": "rv2", "findings": [
        item(location="src/app2.py:88", matches="F-0001"),
        item(problem="AC-G06 red not kept (different path)")]}, "sha256:v2")
    assert ids == ["F-0001", "F-0002"]
    assert r["findings"]["F-0001"]["location"] == "src/app2.py:88"
    assert len(r["findings"]["F-0001"]["history"]) == 2


def test_fix_submitted_and_resolved_github_thread_keep_blocking():
    r = reg()
    import_review(r, {"result_id": "rv1", "findings": [item()]}, K)
    submit_fix(r, "F-0001", "c0ffee", ["sha256:" + "e" * 64])
    record_external(r, "F-0001", {"source": "github", "kind": "thread_resolved", "actor": "implementer"})
    assert r["findings"]["F-0001"]["status"] == "fix_submitted"
    assert open_blocking(r) == ["F-0001"]


def test_reviewer_recheck_or_explicit_human_decision_closes_with_record():
    r = reg()
    import_review(r, {"result_id": "rv1", "findings": [item(), item(problem="second")]}, K)
    close(r, "F-0001", {"actor_kind": "reviewer", "result_id": "rv3", "version_key": K,
                        "reason": "fixed in c0ffee", "evidence": ["sha256:" + "f" * 64]}, K)
    close(r, "F-0002", {"actor_kind": "human", "decision": {"kind": "waive_finding", "finding_id": "F-0002",
                                                            "version_key": K, "actor": "user", "reason": "accepted"}},
          K)
    assert r["findings"]["F-0001"]["status"] == "resolved"
    assert r["findings"]["F-0001"]["closure"]["result_id"] == "rv3"
    assert r["findings"]["F-0002"]["status"] == "waived"
    assert open_blocking(r) == []


@pytest.mark.parametrize("closure", [
    {"actor_kind": "implementer", "reason": "fixed"},
    {"actor_kind": "reviewer", "result_id": "rv3", "version_key": "sha256:old", "reason": "x", "evidence": ["e"]},
    {"actor_kind": "human", "decision": {"kind": "waive_finding", "finding_id": "F-0009", "version_key": K,
                                         "actor": "user", "reason": "x"}},
    {"actor_kind": "github", "event": "approve"},
])
def test_other_closures_are_rejected(closure):
    r = reg()
    import_review(r, {"result_id": "rv1", "findings": [item()]}, K)
    with pytest.raises(ClosureRejected):
        close(r, "F-0001", closure, K)
    assert open_blocking(r) == ["F-0001"]
