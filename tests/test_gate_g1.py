"""Task 2.2: G1 - historical Red validity, replay, controller Green at head, lineage, N/A (AC-G04..G10)."""

from delivery.gates import evaluate_g1

HEAD = "H"
LINEAGE = {("P", "H"), ("R0", "H")}


def anc(a, b):
    return a == b or (a, b) in LINEAGE


def red(**over):
    e = {"kind": "red", "status": "test_failed", "producer": {"tool": "delivery-runner"}, "digest_ok": True,
         "failing_ids": ["tests.test_x::test_add"], "snapshot": {"commit": "R", "parent": "P"},
         "replay": {"status": "test_failed", "failing_ids": ["tests.test_x::test_add"]}}
    e.update(over)
    return e


GREEN = {"head": HEAD, "status": "passed", "producer": {"tool": "controller-runner"},
         "passing_ids": ["tests.test_x::test_add", "tests.test_y::test_other"]}


def task(**over):
    t = {"task_id": "2.3", "change_class": "behavior", "red": [red()]}
    t.update(over)
    return t


def test_red_and_green_on_different_shas_pass_with_lineage():
    a = evaluate_g1([task()], GREEN, HEAD, anc)
    assert a["status"] == "passed"
    assert a["tasks"]["2.3"]["lineage"] == {"red_snapshot": "R", "red_parent": "P", "head": "H"}


def test_evidence_contradicting_summary_fails_with_itemised_reasons():
    for bad, reason in ((red(digest_ok=False), "digest"), (red(status="passed"), "status"),
                        (red(producer={"tool": "agent"}), "producer"),
                        (red(snapshot={"commit": "R", "parent": "X"}), "lineage")):
        a = evaluate_g1([task(red=[bad])], GREEN, HEAD, anc)
        assert a["status"] == "failed", reason
        assert any(reason in r for r in a["reasons"]), (reason, a["reasons"])


def test_only_green_is_missing_red():
    a = evaluate_g1([task(red=[])], GREEN, HEAD, anc)
    assert a["status"] == "missing"


def test_syntax_error_red_is_invalid():
    a = evaluate_g1([task(red=[red(status="collection_error", failing_ids=[])])], GREEN, HEAD, anc)
    assert a["status"] == "failed"
    assert any("collection_error" in r for r in a["reasons"])


def test_replay_alone_cannot_stand_in_for_original_red():
    a = evaluate_g1([task(red=[red(kind="replay_check")])], GREEN, HEAD, anc)
    assert a["status"] == "missing"
    labelled = red(kind="replay_check", red_source="replay_by_decision", decision_id="DEC-4")
    b = evaluate_g1([task(red=[labelled])], GREEN, HEAD, anc)
    assert b["status"] == "passed"
    assert b["tasks"]["2.3"]["red_source"] == "replay_by_decision"


def test_unreproducible_red_is_unknown():
    a = evaluate_g1([task(red=[red(replay={"status": "passed", "failing_ids": []})])], GREEN, HEAD, anc)
    assert a["status"] == "unknown"


def test_integration_regression_fails_even_if_tasks_were_green():
    a = evaluate_g1([task()], {**GREEN, "status": "failed", "failing_ids": ["tests.test_y::test_other"]}, HEAD, anc)
    assert a["status"] == "failed"
    assert any("regression" in r for r in a["reasons"])


def test_worker_reported_green_or_green_at_other_head_is_not_accepted():
    assert evaluate_g1([task()], {**GREEN, "producer": {"tool": "agent"}}, HEAD, anc)["status"] == "failed"
    assert evaluate_g1([task()], {**GREEN, "head": "OLD"}, HEAD, anc)["status"] == "stale"
    assert evaluate_g1([task()], None, HEAD, anc)["status"] == "missing"


def test_accepted_na_for_docs_task_satisfies_red_requirement_only():
    docs = task(task_id="2.9d", change_class="na_requested", red=[],
                na={"status": "accepted", "diff_digest": "D1"}, diff_digest="D1")
    a = evaluate_g1([task(), docs], GREEN, HEAD, anc)
    assert a["status"] == "passed"
    assert "g2" not in a  # eligibility never produces G2


def test_self_declared_pending_or_rejected_na_does_not_pass():
    for na, want in ((None, "failed"), ({"status": "pending", "diff_digest": "D1"}, "pending"),
                     ({"status": "rejected", "diff_digest": "D1", "reason": "config behavior"}, "failed"),
                     ({"status": "accepted", "diff_digest": "OLD"}, "failed")):
        t = task(change_class="na_requested", red=[], na=na, diff_digest="D1")
        assert evaluate_g1([t], GREEN, HEAD, anc)["status"] == want, na


def test_method_changed_flag_does_not_deadlock_deterministic_g1():
    # N-V3-01: method applicability is judged by the new-contract G2; G1 stays deterministic.
    a = evaluate_g1([task(red=[red(method_changed=True)])], GREEN, HEAD, anc)
    assert a["status"] == "passed"
    assert a["tasks"]["2.3"]["method_changed"] is True
