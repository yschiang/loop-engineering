"""Task 2.10 end-to-end paths with fake review/CI inputs: PR binding, base-only change, contract change."""

from delivery.controller import reassess
from delivery.gates import decide_pass, evaluate_g2, evaluate_g3
from delivery.versions import version_key

V1 = {"repo_id": "r", "pr_number": None, "head_sha": "H", "base_ref": "main", "base_tip": "B1", "merge_base": "B1",
      "bindings": {"issue_body": "d1", "plan": "p1"}, "skills": {"superpowers:test-driven-development": "s1"},
      "controller_version": "0.1.0"}
PROFILE = {"model": "gpt-r"}
ISO = {"status": "verified", "profile_digest": "P"}
POLICY = {"required": [{"name": "test", "app": "github-actions", "source": "head"}], "allow_non_success": []}


def start(vs):
    k = version_key(vs)
    return {"phase": "validating", "versions": vs, "pass_history": [], "current_pass": None, "blockers": [],
            "gates": {"g1": {"gate": "g1", "status": "passed", "version_key": k, "evidence": ["sha256:" + "1" * 64]},
                      "g2": {"gate": "g2", "status": "missing", "version_key": k, "evidence": []},
                      "g3": {"gate": "g3", "status": "missing", "version_key": k, "evidence": []}}}


def fresh_review_and_ci(s):
    vs = s["versions"]
    k = version_key(vs)
    rv = {"dispatched_by": "controller", "role": "reviewer", "version_key": k, "verdict": "clean",
          "session_id": "rs", "parent_session_id": None, "requested_model": "gpt-r", "actual_model": "gpt-r",
          "receipt_profile_digest": "P", "read_contract": {x: vs[x] for x in ("head_sha", "base_tip", "bindings",
                                                                              "skills")}}
    s["gates"]["g2"] = {**evaluate_g2(rv, vs, k, PROFILE, ISO, {"is"}, []), "evidence": []}
    ci = [{"name": "test", "app": "github-actions", "head_sha": vs["head_sha"], "status": "completed",
           "conclusion": "success", "started_at": "t", "id": 1}]
    s["gates"]["g3"] = {**evaluate_g3(POLICY, {"test"}, vs["head_sha"], vs["base_tip"], None, ci),
                        "version_key": k, "evidence": []}
    return k


def test_pre_pr_g1_then_pr_binding_then_review_and_ci_reach_pass():
    s = start(V1)
    s = reassess(s, {**V1, "pr_number": 34})
    assert s["gates"]["g1"]["status"] == "passed" and s["phase"] == "checking"
    k = fresh_review_and_ci(s)
    s = decide_pass(s, k, [], reread=lambda: k, now="t1")
    assert s["current_pass"]["version_key"] == k


def test_base_only_change_rechecks_g1_then_passes_or_corrects_on_conflict():
    s = start({**V1, "pr_number": 34})
    s = reassess(s, {**V1, "pr_number": 34, "base_tip": "B2", "merge_base": "B2"},
                 base_recheck={"status": "passed", "evidence": ["sha256:" + "2" * 64]})
    assert s["gates"]["g1"]["derived"]["rule"] == "R-base" and s["phase"] == "checking"
    k = fresh_review_and_ci(s)
    assert decide_pass(s, k, [], reread=lambda: k, now="t2")["current_pass"]["version_key"] == k
    c = start({**V1, "pr_number": 34})
    c = reassess(c, {**V1, "pr_number": 34, "base_tip": "B3", "merge_base": "B3"},
                 base_recheck={"status": "failed", "reason": "base_conflict"})
    assert c["phase"] == "correcting"


def test_contract_change_needs_new_evidence_and_new_contract_review_before_pass():
    s = start({**V1, "pr_number": 34})
    fresh_review_and_ci(s)
    v4 = {**V1, "pr_number": 34, "bindings": {"issue_body": "d2", "plan": "p2"}}
    s = reassess(s, v4, reevaluate=lambda a, vs: ("missing", ["AC-X02 has no evidence"]))
    assert s["gates"]["g2"]["status"] == "stale" and s["gates"]["g1"]["status"] == "missing"
    assert s["phase"] == "implementing"
    k = version_key(v4)
    assert decide_pass(s, k, [], reread=lambda: k, now="t3")["current_pass"] is None
    s["gates"]["g1"] = {"gate": "g1", "status": "passed", "version_key": k, "evidence": ["sha256:" + "3" * 64]}
    fresh_review_and_ci(s)
    assert decide_pass(s, k, [], reread=lambda: k, now="t4")["current_pass"]["version_key"] == k
