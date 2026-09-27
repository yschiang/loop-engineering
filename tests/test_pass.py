"""Task 2.5: PR Pass only for three passed gates on one version, re-read before recording (AC-G01, G02, G18)."""

import copy

from delivery.gates import decide_pass, observe_new_version

K = "sha256:v1"


def state(g1="passed", g2="passed", g3="passed", keys=(K, K, K)):
    return {"phase": "checking", "pass_history": [], "current_pass": None,
            "tasks": [{"task_id": "2.3", "status": "succeeded"}],
            "gates": {g: {"gate": g, "status": s, "version_key": k}
                      for g, s, k in zip(("g1", "g2", "g3"), (g1, g2, g3), keys, strict=True)}}


def test_three_passed_gates_on_current_version_record_pass():
    s = decide_pass(state(), K, [], reread=lambda: K, now="t1")
    assert s["phase"] == "ready_for_acceptance"
    assert s["current_pass"] == {"version_key": K, "observed_at": "t1",
                                 "gates": {"g1": K, "g2": K, "g3": K}}


def test_task_success_alone_or_one_gate_on_other_version_does_not_pass():
    s = decide_pass(state(g2="pending"), K, [], reread=lambda: K, now="t1")
    assert s["current_pass"] is None and s["phase"] == "checking"
    s = decide_pass(state(keys=(K, K, "sha256:v0")), K, [], reread=lambda: K, now="t1")
    assert s["current_pass"] is None


def test_review_clean_with_ci_failed_keeps_both_results_and_no_pass():
    before = state(g3="failed")
    s = decide_pass(copy.deepcopy(before), K, [], reread=lambda: K, now="t1")
    assert s["current_pass"] is None
    assert s["gates"] == before["gates"]


def test_open_blocking_finding_prevents_pass():
    assert decide_pass(state(), K, ["F-0002"], reread=lambda: K, now="t1")["current_pass"] is None


def test_reread_mismatch_abandons_pass_and_requests_reconcile():
    s = decide_pass(state(), K, [], reread=lambda: "sha256:v2", now="t1")
    assert s["current_pass"] is None
    assert s["next_action"]["kind"] == "reconcile"


def test_push_after_pass_invalidates_current_but_keeps_history():
    s = decide_pass(state(), K, [], reread=lambda: K, now="t1")
    s = observe_new_version(s, "sha256:v2", now="t2")
    assert s["current_pass"] is None
    assert s["pass_history"][-1]["version_key"] == K
    assert s["pass_history"][-1]["invalidated_at"] == "t2"
    assert s["phase"] == "validating"
