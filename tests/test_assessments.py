"""Task 2.1 (DR-03/DR-10): dependency matrix completeness and derivation rules."""

from delivery.versions import GATES, derive, matrix_rows, version_key

V1 = {"repo_id": "r", "pr_number": None, "head_sha": "h1", "base_ref": "main", "base_tip": "b1", "merge_base": "b1",
      "bindings": {"issue_body": "d1", "plan": "p1"}, "skills": {"superpowers:test-driven-development": "s1"},
      "controller_version": "0.1.0"}


def with_(**over):
    v = {**V1, **over}
    return v


def passed(gate, vs, evidence=("sha256:" + "a" * 64,)):
    return {"gate": gate, "version_key": version_key(vs), "status": "passed", "evidence": list(evidence)}


def test_every_version_set_field_has_a_cell_for_every_gate():
    rows = matrix_rows()
    for field in ("repo_id", "pr_number", "head_sha", "base_ref", "base_tip", "merge_base", "controller_version",
                  "skills.superpowers:test-driven-development", "bindings.issue_body", "bindings.plan"):
        assert set(rows[field]) == set(GATES), field


def test_first_pr_binding_carries_g1_without_touching_evidence():
    v2 = with_(pr_number=34)
    a = derive(passed("g1", V1), V1, v2)
    assert a["status"] == "passed" and a["version_key"] == version_key(v2)
    assert a["evidence"] == passed("g1", V1)["evidence"]
    assert a["derived"]["rule"] == "R-unaffected" and a["derived"]["changed_fields"] == ["pr_number"]


def test_base_change_requires_recheck_evidence_for_g1():
    v3 = with_(base_tip="b2", merge_base="b2")
    assert derive(passed("g1", V1), V1, v3)["status"] == "stale"
    rechecked = derive(passed("g1", V1), V1, v3,
                       base_recheck={"status": "passed", "evidence": ["sha256:" + "b" * 64]})
    assert rechecked["status"] == "passed" and rechecked["derived"]["rule"] == "R-base"
    conflict = derive(passed("g1", V1), V1, v3, base_recheck={"status": "failed", "reason": "base_conflict"})
    assert conflict["status"] == "failed"


def test_contract_change_makes_g2_stale_and_g1_reevaluated():
    v4 = with_(bindings={"issue_body": "d2", "plan": "p2"})
    assert derive(passed("g2", V1), V1, v4)["status"] == "stale"
    g1 = derive(passed("g1", V1), V1, v4, reevaluate=lambda a, vs: ("missing", ["AC-X02 has no evidence"]))
    assert g1["status"] == "missing" and g1["derived"]["rule"] == "R-reevaluate"


def test_skill_change_marks_method_changed_and_stales_g2():
    v5 = with_(skills={"superpowers:test-driven-development": "s2"})
    g1 = derive(passed("g1", V1), V1, v5, reevaluate=lambda a, vs: ("passed", []))
    assert g1["derived"]["method_changed"] is True
    assert derive(passed("g2", V1), V1, v5)["status"] == "stale"
    assert derive(passed("g3", V1), V1, v5)["status"] == "pending"  # G3 always re-observed


def test_unknown_field_or_skill_is_treated_as_dependency():
    v6 = with_(skills={**V1["skills"], "mystery-skill": "x"})
    for gate in GATES:
        assert derive(passed(gate, V1), V1, v6)["status"] == "stale"
    v7 = {**V1, "new_field": 1}
    for gate in GATES:
        assert derive(passed(gate, V1), V1, v7)["status"] == "stale"


def test_controller_upgrade_recomputes_and_stricter_evaluator_can_fail():
    v8 = with_(controller_version="0.2.0")
    g1 = derive(passed("g1", V1), V1, v8, reevaluate=lambda a, vs: ("failed", ["stricter red rule"]))
    assert g1["status"] == "failed" and g1["derived"]["rule"] == "R-reevaluate"
    assert derive(passed("g3", V1), V1, v8)["status"] == "pending"


def test_g3_is_never_carried_across_any_key_change():
    for change in ({"pr_number": 34}, {"head_sha": "h2"}, {"base_tip": "b9"}):
        assert derive(passed("g3", V1), V1, with_(**change))["status"] == "pending"
