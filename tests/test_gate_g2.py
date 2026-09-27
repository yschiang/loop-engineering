"""Task 2.3 (DR-01, DR-10): G2 only from a controller-dispatched, isolated, current-contract review."""

from delivery.gates import evaluate_g2

VS = {"head_sha": "H", "base_tip": "B", "bindings": {"issue_body": "d2", "plan": "p2"},
      "skills": {"superpowers:test-driven-development": "s1"}}
KEY = "sha256:current"
PROFILE = {"runtime": "opencode", "provider": "openai", "model": "gpt-reviewer-x"}
ISO = {"status": "verified", "profile_digest": "P1"}


def review(**over):
    r = {"dispatched_by": "controller", "role": "reviewer", "version_key": KEY, "verdict": "clean",
         "session_id": "rs1", "parent_session_id": None, "requested_model": "gpt-reviewer-x",
         "actual_model": "gpt-reviewer-x", "receipt_profile_digest": "P1",
         "read_contract": {"head_sha": "H", "base_tip": "B", "bindings": {"issue_body": "d2", "plan": "p2"},
                           "skills": {"superpowers:test-driven-development": "s1"}}}
    r.update(over)
    return r


def g2(r=None, iso=ISO, impl=frozenset({"is1"}), findings=()):
    return evaluate_g2(r if r is not None else review(), VS, KEY, PROFILE, iso, set(impl), list(findings))


def test_valid_new_contract_review_passes():
    a = g2()
    assert a["status"] == "passed"
    assert a["version_key"] == KEY


def test_implementer_subagent_review_is_not_g2():
    assert g2(review(dispatched_by="implementer"))["status"] == "unknown"
    assert g2(review(parent_session_id="is1"))["status"] == "unknown"
    assert g2(review(session_id="is1"))["status"] == "unknown"


def test_clone_and_env_scrub_without_verified_report_is_unknown():
    a = g2(iso={"status": "unverified", "profile_digest": "P1", "note": "clone+env scrub+refs unchanged"})
    assert a["status"] == "unknown"
    assert any("isolation" in r for r in a["reasons"])
    assert g2(iso=None)["status"] == "unknown"


def test_receipt_profile_digest_must_match_verified_report():
    assert g2(review(receipt_profile_digest="P9"))["status"] == "unknown"


def test_actual_model_must_match_approved_profile():
    assert g2(review(actual_model="gpt-other"))["status"] == "unknown"


def test_review_must_have_read_current_binding_digests():
    stale_contract = review(read_contract={**review()["read_contract"], "bindings": {"issue_body": "d1",
                                                                                     "plan": "p2"}})
    assert g2(stale_contract)["status"] == "unknown"
    partial = review(read_contract={"head_sha": "H", "base_tip": "B", "bindings": {"issue_body": "d2"},
                                    "skills": {"superpowers:test-driven-development": "s1"}})
    assert g2(partial)["status"] == "unknown"


def test_review_for_other_version_is_stale():
    assert g2(review(version_key="sha256:old"))["status"] == "stale"


def test_blocked_verdict_is_unknown_blocks_feature_and_opens_no_round():
    a = g2(review(verdict="blocked"))
    assert a["status"] == "unknown"
    assert a["blocks_feature"] is True and a["opens_correction_round"] is False


def test_changes_required_or_open_blocking_finding_fails():
    assert g2(review(verdict="changes_required"))["status"] == "failed"
    assert g2(findings=["F-0003"])["status"] == "failed"


def test_missing_review_is_missing():
    assert evaluate_g2(None, VS, KEY, PROFILE, ISO, set(), [])["status"] == "missing"
