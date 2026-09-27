"""Task 2.7: batches, 3-round cap, one dispute, recurrence (AC-F05..F10, F15, F16)."""

import copy
import json

from delivery.correction import (
    check_result,
    dispatch_batch,
    ready_for_batch,
    record_recheck,
    reopen,
    request_dispute_review,
    settle_dispute,
)
from delivery.findings import import_review

K = "sha256:v1"


def st():
    s = {"budget": {"correction_rounds_used": 0}, "batches": [], "disputes": {}, "blockers": [],
         "registry": {"seq": 0, "findings": {}}}
    import_review(s["registry"], {"result_id": "rv1", "findings": [
        {"category": "spec_ac", "problem": "p1"}, {"category": "spec_ac", "problem": "p2"}]}, K)
    return s


def test_ci_failure_waits_for_same_version_review_then_one_batch_one_round():
    assert not ready_for_batch({"status": "pending"}, {"status": "failed"})
    assert ready_for_batch({"status": "failed"}, {"status": "failed"})
    s = st()
    out = dispatch_batch(s, K, ["F-0001", "F-0002"], ["test: failure"])
    assert out["dispatched"] is True
    assert s["budget"]["correction_rounds_used"] == 1
    assert s["batches"][-1]["items"] == {"findings": ["F-0001", "F-0002"], "ci": ["test: failure"],
                                         "base_conflict": False}


def test_incomplete_correction_result_lists_missing_ids():
    s = st()
    batch = dispatch_batch(s, K, ["F-0001", "F-0002"], [])["batch"]
    missing = check_result(batch, {"responses": {"F-0001": {"kind": "fix_submitted", "commit": "c1"}}})
    assert missing == ["F-0002"]


def test_fourth_round_is_never_dispatched_and_rounds_survive_restart():
    s = st()
    for _ in range(3):
        assert dispatch_batch(s, K, ["F-0001"], [])["dispatched"]
    restarted = json.loads(json.dumps(s))
    out = dispatch_batch(restarted, K, ["F-0001"], [])
    assert out["dispatched"] is False
    assert restarted["budget"]["correction_rounds_used"] == 3
    assert any(b["kind"] == "correction_rounds_exhausted" for b in restarted["blockers"])


def test_base_conflict_is_a_batch_item():
    s = st()
    batch = dispatch_batch(s, K, [], [], base_conflict=True)["batch"]
    assert batch["items"]["base_conflict"] is True


def test_accepted_dispute_resolves_without_a_new_round():
    s = st()
    dispatch_batch(s, K, ["F-0001"], [])
    step = request_dispute_review(s, "F-0001", "sha256:" + "d" * 64, new_head=False)
    assert step["next"] == "dispute_review"
    settle_dispute(s, "F-0001", reviewer_accepts=True)
    assert s["registry"]["findings"]["F-0001"]["status"] == "resolved"
    assert s["budget"]["correction_rounds_used"] == 1


def test_upheld_dispute_blocks_and_a_resent_dispute_after_restart_gets_no_second_review():
    s = st()
    request_dispute_review(s, "F-0001", "sha256:" + "d" * 64, new_head=False)
    settle_dispute(s, "F-0001", reviewer_accepts=False)
    assert any(b["kind"] == "dispute_upheld" for b in s["blockers"])
    restarted = copy.deepcopy(s)
    again = request_dispute_review(restarted, "F-0001", "sha256:" + "d" * 64, new_head=False)
    assert again["next"] == "blocked"
    assert restarted["disputes"]["F-0001"]["reviews_used"] == 1


def test_dispute_with_new_head_goes_through_g1_first():
    s = st()
    assert request_dispute_review(s, "F-0001", "sha256:" + "d" * 64, new_head=True)["next"] == "validating"


def test_two_failed_rechecks_block_before_next_dispatch():
    s = st()
    for i in (1, 2):
        dispatch_batch(s, K, ["F-0001"], [])
        record_recheck(s, "F-0001", still_open=True, batch_id=f"b{i}", result_id=f"rv{i + 1}")
    out = dispatch_batch(s, K, ["F-0001"], [])
    assert out["dispatched"] is False
    assert any(b["kind"] == "recurrence" and b["finding_id"] == "F-0001" for b in s["blockers"])
    assert s["budget"]["correction_rounds_used"] == 2


def test_duplicate_recheck_result_is_not_counted_twice():
    s = st()
    record_recheck(s, "F-0001", still_open=True, batch_id="b1", result_id="rv2")
    record_recheck(s, "F-0001", still_open=True, batch_id="b1", result_id="rv2")
    assert s["registry"]["findings"]["F-0001"]["failed_rechecks"] == 1


def test_reopened_finding_blocks_early():
    s = st()
    s["registry"]["findings"]["F-0001"]["status"] = "resolved"
    reopen(s, "F-0001", reviewer_basis="same defect reappears in src/app.py:12")
    assert s["registry"]["findings"]["F-0001"]["status"] == "open"
    assert dispatch_batch(s, K, ["F-0001"], [])["dispatched"] is False
