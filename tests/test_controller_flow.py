"""Task 2.10 (partial): intake routing, dispatch authorization, dependencies, drafts, cross-feature impact."""

from delivery.controller import authorize_dispatch, dependency_ready, mark_cross_feature_impact, route_intake

OK = {"owner_handoff": True, "unknown_writers": [], "sources": {"conflicts": [], "unreadable": []}}


def test_direct_to_implementer_enters_planning_keeping_identities():
    r = route_intake({**OK, "kind": "new", "feature_owner": "yschiang", "controller_run": "r1"})
    assert r["phase"] == "planning" and r["feature_owner"] == "yschiang" and r["controller_run"] == "r1"


def test_conflicting_or_unreadable_sources_block_with_versions():
    r = route_intake({**OK, "kind": "new", "sources": {"conflicts": [{"a": "spec@v3", "b": "issue@v7"}],
                                                       "unreadable": []}})
    assert r["phase"] == "blocked" and r["blockers"][0]["seen"] == [{"a": "spec@v3", "b": "issue@v7"}]


def test_adopt_routes_by_existing_evidence_and_reports_each_gap():
    base = {**OK, "kind": "adopt", "has_plan": True, "d11": True, "tasks_done": True, "g1_verified": False,
            "fixed_base": True, "historical_red": True}
    assert route_intake(base)["phase"] == "validating"
    assert route_intake({**base, "g1_verified": True})["phase"] == "checking"
    assert route_intake({**base, "tasks_done": False})["phase"] == "implementing"
    assert route_intake({**base, "d11": False})["phase"] == "awaiting_approval"
    gaps = route_intake({**base, "historical_red": False, "fixed_base": False, "unknown_writers": ["pid 42"]})
    assert gaps["phase"] == "blocked"
    assert {b["kind"] for b in gaps["blockers"]} == {"missing_historical_red", "unfixed_base", "unknown_writer"}
    assert route_intake({**base, "owner_handoff": False})["phase"] == "blocked"


def st(**over):
    s = {"approval": {"plan_version": "P2", "plan_producer": "implementer"}, "plan_version": "P2",
         "tasks": {"2.3": {"status": "pending", "scope": ["src"]}}, "budget_ok": True, "deps_ready": True,
         "blockers": []}
    s.update(over)
    return s


def req(**over):
    r = {"task_id": "2.3", "via": "controller", "requested_by": "implementer", "authorization": None,
         "runtime_parent": None}
    r.update(over)
    return r


def test_only_controller_dispatch_with_approved_plan_is_accepted():
    assert authorize_dispatch(st(), req())["accepted"] is True
    assert authorize_dispatch(st(), req(via="skill"))["accepted"] is False
    assert authorize_dispatch(st(), req(via="other_session"))["accepted"] is False


def test_sa_confirmation_without_d11_never_dispatches():
    s = st(approval=None, sa_confirmation={"version": "SA1"})
    assert authorize_dispatch(s, req())["accepted"] is False


def test_project_lead_needs_authorisation_source_and_parent_session_grants_nothing():
    s = st()
    assert authorize_dispatch(s, req(requested_by="project_lead"))["accepted"] is False
    auth = {"source": "chat:88", "scope": ["2.3"]}
    assert authorize_dispatch(s, req(requested_by="project_lead", authorization=auth))["accepted"] is True
    parent_only = req(requested_by="project_lead", runtime_parent="implementer-session")
    assert authorize_dispatch(s, parent_only)["accepted"] is False


def test_project_lead_draft_plan_is_not_dispatchable():
    s = st(approval={"plan_version": "P2", "plan_producer": "project_lead_draft"})
    assert authorize_dispatch(s, req())["accepted"] is False


def test_upstream_accepted_but_unmerged_waits_and_merged_in_baseline_releases():
    dep = {"feature": "F0", "version": "v9", "accepted_versions": ["v9"], "merged": False, "merge_commit": None}
    assert dependency_ready(dep, lambda a, b: True, "BASE")["ready"] is False
    merged = {**dep, "merged": True, "merge_commit": "M9"}
    assert dependency_ready(merged, lambda a, b: False, "BASE")["ready"] is False  # baseline lacks it
    assert dependency_ready(merged, lambda a, b: (a, b) == ("M9", "BASE"), "BASE")["ready"] is True
    assert dependency_ready({**merged, "accepted_versions": ["v8"]}, lambda a, b: True, "BASE")["ready"] is False


def test_cross_feature_impact_blocks_only_affected_tasks():
    s = st(tasks={"2.3": {"status": "pending", "scope": ["src"]}, "2.4": {"status": "pending", "scope": ["src"]}})
    mark_cross_feature_impact(s, ["2.3"], "changes contract used by F2")
    assert authorize_dispatch(s, req(task_id="2.3"))["accepted"] is False
    assert authorize_dispatch(s, req(task_id="2.4"))["accepted"] is True
