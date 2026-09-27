"""Task 2.4 (DR-08): G3 required checks, attempts, app source, head/merge SHA selection (AC-G13..G15)."""

import pytest

from delivery.gates import evaluate_g3

H, B, M = "h" * 40, "b" * 40, "m" * 40
POLICY = {"required": [{"name": "test", "app": "github-actions", "source": "head"}], "allow_non_success": []}


def check(**over):
    c = {"name": "test", "app": "github-actions", "head_sha": H, "status": "completed", "conclusion": "success",
         "started_at": "2026-09-27T05:00:00Z", "id": 1}
    c.update(over)
    return c


def g3(checks, policy=POLICY, rules=frozenset({"test"}), merge=None, base=B):
    return evaluate_g3(policy, set(rules) if rules is not None else None, H, base, merge, checks)


def test_success_on_head_passes():
    assert g3([check()])["status"] == "passed"


@pytest.mark.parametrize("checks,want,why", [
    ([], "missing", "missing"),
    ([check(status="in_progress", conclusion=None)], "pending", "pending"),
    ([check(conclusion="cancelled")], "failed", "cancelled"),
    ([check(conclusion="timed_out")], "failed", "timed_out"),
    ([check(conclusion="failure")], "failed", "failure"),
    ([check(conclusion="mystery")], "unknown", "mystery"),
    ([check(head_sha="o" * 40)], "stale", "stale"),
])
def test_seven_non_success_states_never_pass(checks, want, why):
    a = g3(checks)
    assert a["status"] == want
    assert any(why in r for r in a["reasons"]), a["reasons"]


def test_skipped_or_neutral_needs_explicit_policy_decision():
    assert g3([check(conclusion="skipped")])["status"] == "failed"
    assert g3([check(conclusion="neutral")])["status"] == "failed"
    allow = {**POLICY, "allow_non_success": [{"name": "test", "conclusions": ["skipped"], "decision": "DEC-7"}]}
    assert g3([check(conclusion="skipped")], policy=allow)["status"] == "passed"
    assert g3([check(conclusion="neutral")], policy=allow)["status"] == "failed"


def test_empty_required_set_or_unreadable_or_mismatched_rules_do_not_pass():
    assert g3([check()], policy={**POLICY, "required": []})["status"] == "failed"
    assert g3([check()], rules=None)["status"] == "unknown"
    assert g3([check()], rules={"test", "lint"})["status"] == "failed"


def test_latest_attempt_wins_over_older_success():
    older = check(id=1, started_at="2026-09-27T05:00:00Z", conclusion="success")
    newer = check(id=2, started_at="2026-09-27T06:00:00Z", status="in_progress", conclusion=None)
    assert g3([older, newer])["status"] == "pending"


def test_same_name_from_unknown_app_is_ignored():
    assert g3([check(app="some-bot")])["status"] == "missing"


MERGE_POLICY = {"required": [{"name": "test", "app": "github-actions", "source": "merge"}], "allow_non_success": []}


def test_merge_source_check_on_verified_m_is_used():
    merge = {"sha": M, "parents": [B, H]}
    a = g3([check(head_sha=M)], policy=MERGE_POLICY, merge=merge)
    assert a["status"] == "passed"
    assert a["merge_mapping"] == merge


def test_merge_for_old_base_is_stale_and_uncomputed_merge_is_unknown():
    old = {"sha": M, "parents": ["0" * 40, H]}
    assert g3([check(head_sha=M)], policy=MERGE_POLICY, merge=old)["status"] == "stale"
    assert g3([check(head_sha=M)], policy=MERGE_POLICY, merge=None)["status"] == "unknown"
