"""Task 2.12: publication traceability, publication state separate from verdict, readable status."""

import copy

from delivery.outbox import advance
from delivery.publication import publication_status, register_publication, render_status
from delivery.store import Store

from .fakes import FakeGitHub

REVIEW = {"result_id": "rv7", "review_id": "R-3", "verdict": "changes_required", "version_key": "vk:v1",
          "head": "H1", "base": "B1", "spec": "d1",
          "findings": [{"id": "F-0001", "blocking": True, "problem": "red lost", "expected": "kept"},
                       {"id": "F-0002", "blocking": False, "problem": "naming", "expected": "clearer"}]}


def st():
    return {"schema_version": 1, "phase": "checking", "operations": {}, "blockers": [],
            "gates": {"g2": {"status": "failed", "version_key": "vk:v1", "reasons": ["verdict changes_required"]}}}


def test_pr_gets_full_review_and_issue_gets_actionable_summary_with_link(tmp_path):
    s = st()
    pr_op, issue_op = register_publication(s, "r1", REVIEW)
    store = Store(tmp_path)
    store.commit(s)
    gh = FakeGitHub()
    s = advance(store, s, pr_op, github=gh)
    s = advance(store, s, issue_op, github=gh)
    pr_body = gh.comments["pr"][0]
    issue_body = gh.comments["issue"][0]
    for text in ("r1", "R-3", "rv7", "vk:v1", "H1", "B1", "F-0001", "F-0002", "red lost", "changes_required"):
        assert text in pr_body, text
    assert "F-0001" in issue_body and "https://gh/pr#c1" in issue_body and "rv7" in issue_body
    assert "naming" not in issue_body  # summary lists actionable blocking items only
    assert publication_status(s, (pr_op, issue_op)) == "published"


def test_failed_publication_keeps_review_and_verdict_and_is_not_published(tmp_path):
    s = st()
    ops = register_publication(s, "r1", REVIEW)
    store = Store(tmp_path)
    store.commit(s)
    before = copy.deepcopy(s["gates"])
    s = advance(store, s, ops[0], github=FakeGitHub(faults=["error", "error", "error"]))
    assert s["gates"] == before
    assert publication_status(s, ops) == "blocked"
    assert s["operations"][ops[1]]["state"] == "pending"


def test_status_shows_phase_version_gate_reasons_blockers_and_next_action():
    s = st()
    s.update(next_action={"kind": "wait_review", "detail": "R-4 dispatched"},
             blockers=[{"kind": "dispute_upheld", "finding_id": "F-0001"}],
             versions_key="vk:v1", budget={"correction_rounds_used": 1, "active_seconds": 3600})
    out = render_status(s)
    for text in ("checking", "vk:v1", "g2", "failed", "verdict changes_required", "dispute_upheld", "F-0001",
                 "wait_review", "rounds 1/3"):
        assert text in out, text
