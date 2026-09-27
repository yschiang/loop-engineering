"""Task 2.8: versioned human decisions, acceptance and returns (AC-O05..O07, O10, O11, F11, F12, D02)."""

import pytest

from delivery.decisions import DecisionInvalid, acceptance_for, apply_decision, may_dispatch_implementation


def st(**over):
    s = {"phase": "awaiting_approval", "plan_version": "sha256:plan2", "approval": None, "current_pass": None,
         "pass_history": [], "acceptance": {"history": []}, "blockers": [], "operations": {},
         "budget": {"correction_rounds_used": 1, "extensions": []}, "registry": {"seq": 0, "findings": {}},
         "pending_scope": []}
    s.update(over)
    return s


def d(kind, **over):
    x = {"decision_id": f"DEC-{kind}", "kind": kind, "actor": "user", "actor_kind": "human", "source": "chat:42",
         "reason": "ok", "created_at": "t1", "subject": {}}
    x.update(over)
    return x


def test_no_decision_agent_consent_or_timeout_is_not_approval():
    s = st()
    assert not may_dispatch_implementation(s)
    with pytest.raises(DecisionInvalid):
        apply_decision(s, d("approve_plan", actor_kind="agent", subject={"plan_version": "sha256:plan2"}))
    with pytest.raises(DecisionInvalid):
        apply_decision(s, d("approve_plan", actor_kind="timeout", subject={"plan_version": "sha256:plan2"}))
    assert not may_dispatch_implementation(s) and s["phase"] == "awaiting_approval"


def test_approval_binds_to_the_current_plan_version_only():
    s = apply_decision(st(), d("approve_plan", subject={"plan_version": "sha256:plan2"}))
    assert may_dispatch_implementation(s) and s["phase"] == "implementing"
    s["plan_version"] = "sha256:plan3"
    assert not may_dispatch_implementation(s)
    with pytest.raises(DecisionInvalid):
        apply_decision(st(), d("approve_plan", subject={"plan_version": "sha256:plan1"}))


def test_scope_change_waits_for_a_new_versioned_approval():
    s = apply_decision(st(phase="correcting"), d("scope_change", subject={"items": ["add AC-X9"],
                                                                         "impact": "new endpoint"}))
    assert s["phase"] == "awaiting_approval"
    assert s["pending_scope"] == [{"items": ["add AC-X9"], "impact": "new endpoint"}]
    assert not may_dispatch_implementation(s)


def test_pass_without_acceptance_is_pending_and_no_merge_operation_exists():
    s = st(phase="ready_for_acceptance", current_pass={"version_key": "sha256:v1"})
    assert acceptance_for(s, "sha256:v1") == "pending"
    assert all(op["kind"] not in ("merge", "close_issue", "release", "deploy") for op in s["operations"].values())


def test_acceptance_of_v1_is_not_carried_to_v2():
    s = st(phase="ready_for_acceptance", current_pass={"version_key": "sha256:v1"})
    apply_decision(s, d("accept", subject={"version_key": "sha256:v1"}))
    assert acceptance_for(s, "sha256:v1") == "accepted"
    assert acceptance_for(s, "sha256:v2") == "pending"
    with pytest.raises(DecisionInvalid):
        apply_decision(s, d("accept", subject={"version_key": "sha256:v0"}))


def test_return_for_ac_defect_creates_human_finding_invalidates_pass_and_corrects():
    s = st(phase="ready_for_acceptance", current_pass={"version_key": "sha256:v1"},
           pass_history=[{"version_key": "sha256:v1"}])
    ret = d("return", subject={"version_key": "sha256:v1", "category": "ac_defect", "ac_id": "AC-G06",
                               "difference": "red lost for untracked test", "feedback_id": "fb-1"})
    apply_decision(s, ret)
    apply_decision(s, dict(ret, decision_id="DEC-return-dup"))  # same feedback resent
    findings = list(s["registry"]["findings"].values())
    assert len(findings) == 1 and findings[0]["source"] == "human_acceptance" and findings[0]["blocking"]
    assert s["current_pass"] is None and s["phase"] == "correcting"


def test_return_for_new_scope_or_spec_error_goes_back_to_people_not_correction():
    for cat in ("new_scope", "spec_error"):
        s = st(phase="ready_for_acceptance", current_pass={"version_key": "sha256:v1"})
        apply_decision(s, d("return", subject={"version_key": "sha256:v1", "category": cat, "feedback_id": "f"}))
        assert s["phase"] == "blocked"
        assert s["blockers"][-1]["route"] == "project_lead_and_user"
        assert s["registry"]["findings"] == {}


def test_gate_edits_and_incomplete_decisions_are_rejected():
    with pytest.raises(DecisionInvalid):
        apply_decision(st(), d("set_gate", subject={"g1": "passed"}))
    with pytest.raises(DecisionInvalid):
        apply_decision(st(), {k: v for k, v in d("approve_plan").items() if k != "source"})


def test_budget_extension_is_recorded_as_decision():
    s = apply_decision(st(), d("budget_extension", subject={"seconds": 1800}))
    assert s["budget"]["extensions"] == [{"decision_id": "DEC-budget_extension", "seconds": 1800}]


def loop_state(**over):
    from delivery.versions import version_key

    vs = {"repo_id": "r", "pr_number": 3, "head_sha": "H", "base_ref": "main", "base_tip": "B", "merge_base": "B",
          "bindings": {"plan": "P2", "policy": "pol1"}, "skills": {}, "controller_version": "0.1.0"}
    k = version_key(vs)
    s = st(versions=vs, tasks=[{"task_id": "t1", "scope": ["src"], "status": "succeeded"}], batches=[],
           gates={g: {"gate": g, "status": "passed", "version_key": k, "evidence": []} for g in ("g1", "g2", "g3")},
           integration={"log": []})
    s.update(over)
    return s, k


def test_revise_clears_approval_and_returns_to_planning():
    s = apply_decision(st(approval={"plan_version": "sha256:plan2", "plan_producer": "implementer"},
                          phase="implementing"), d("revise"))
    assert s["phase"] == "planning" and s["approval"] is None


def test_unblock_requires_a_matching_blocker_and_valid_resume_phase():
    s = st(phase="blocked", blockers=[{"kind": "dispute_upheld", "finding_id": "F-1"}])
    with pytest.raises(DecisionInvalid):
        apply_decision(s, d("unblock", subject={"blocker_kind": "other", "resume_to": "checking"}))
    with pytest.raises(DecisionInvalid):
        apply_decision(s, d("unblock", subject={"blocker_kind": "dispute_upheld", "resume_to": "ready_for_acceptance"}))
    apply_decision(s, d("unblock", subject={"blocker_kind": "dispute_upheld", "resume_to": "checking"}))
    assert s["phase"] == "checking" and s["blockers"] == []


def test_resolve_and_waive_close_the_named_finding_for_the_current_version():
    s, k = loop_state()
    s["registry"] = {"seq": 2, "findings": {f"F-000{i}": {"id": f"F-000{i}", "blocking": True, "status": "open"}
                                           for i in (1, 2)}}
    apply_decision(s, d("resolve_finding", subject={"finding_id": "F-0001", "version_key": k}))
    apply_decision(s, d("waive_finding", subject={"finding_id": "F-0002", "version_key": k}))
    assert [f["status"] for f in s["registry"]["findings"].values()] == ["resolved", "waived"]
    with pytest.raises(DecisionInvalid):
        apply_decision(s, d("waive_finding", subject={"finding_id": "F-0002", "version_key": "vk:old"}))


def test_policy_change_needs_a_policy_digest_and_reassesses_gates():
    s, _ = loop_state()
    with pytest.raises(DecisionInvalid):
        apply_decision(s, d("policy_change", subject={}))
    apply_decision(s, d("policy_change", subject={"policy_digest": "pol2"}))
    assert s["versions"]["bindings"]["policy"] == "pol2" and s["gates"]["g3"]["status"] == "pending"


def test_abandon_run_is_not_silently_accepted_here():
    with pytest.raises(DecisionInvalid, match="authority"):
        apply_decision(st(), d("abandon_run", subject={"run_id": "r1"}))


def test_accept_registers_one_retro_operation():
    s = st(phase="ready_for_acceptance", current_pass={"version_key": "sha256:v1"}, feature_key="o/r#1")
    apply_decision(s, d("accept", subject={"version_key": "sha256:v1"}))
    retro = [o for o in s["operations"].values() if o["kind"] == "retro"]
    assert len(retro) == 1 and retro[0]["state"] == "pending"


def test_ac_defect_return_creates_real_fix_work():
    s, k = loop_state(phase="ready_for_acceptance", current_pass={"version_key": "vk:x"})
    s["current_pass"] = {"version_key": k}
    apply_decision(s, d("return", subject={"version_key": k, "category": "ac_defect", "ac_id": "AC-X1",
                                           "difference": "wrong sum", "feedback_id": "fb-9"}))
    assert s["phase"] == "correcting"
    assert s["batches"][-1]["items"]["findings"] == ["F-0001"]
    assert s["tasks"][-1]["batch_id"] == s["batches"][-1]["batch_id"] and s["tasks"][-1]["status"] == "pending"
