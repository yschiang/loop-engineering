"""Task 2.1: bindings vs observations, version_key stability, adopt_binding decisions (AC-O03, G16, G17)."""

import copy

import pytest

from delivery.versions import DecisionRejected, adopt_binding, observe_binding, version_key, version_set

BODY = b"## Feature\nAC-X01 ...\n"


def base_state():
    s = {"schema_version": 1, "phase": "checking", "bindings": {}, "candidates": {},
         "facts": {"repo_id": "github:yschiang/orca-delivery", "pr_number": None, "head_sha": "h1",
                   "base_ref": "main", "base_tip": "b1", "merge_base": "b1"},
         "skills": {"superpowers:test-driven-development": "bf1b"}, "controller_version": "0.1.0"}
    observe_binding(s, "issue_body", "yschiang/orca-delivery#1", BODY, "t0")
    return s


def test_identical_body_polled_ten_times_and_after_restart_keeps_version_key():
    s = base_state()
    k1 = version_key(version_set(s))
    review = {"gate": "g2", "version_key": k1, "status": "passed"}
    for i in range(10):
        assert observe_binding(s, "issue_body", "yschiang/orca-delivery#1", BODY, f"t{i + 1}") == "unchanged"
    restarted = copy.deepcopy(s)
    observe_binding(restarted, "issue_body", "yschiang/orca-delivery#1", BODY, "t99")
    assert version_key(version_set(restarted)) == k1 == review["version_key"]
    assert restarted["bindings"]["issue_body"]["last_observed_at"] == "t99"
    assert restarted["bindings"]["issue_body"]["adopted_at"] == "t0"


def test_one_byte_body_change_creates_candidate_and_awaits_approval():
    s = base_state()
    k1 = version_key(version_set(s))
    assert observe_binding(s, "issue_body", "yschiang/orca-delivery#1", BODY + b"!", "t1") == "candidate"
    assert s["phase"] == "awaiting_approval"
    assert "issue_body" in s["candidates"]
    assert version_key(version_set(s)) == k1  # not adopted yet


def test_adopt_binding_changes_version_and_rejects_reuse_field():
    s = base_state()
    k1 = version_key(version_set(s))
    observe_binding(s, "issue_body", "yschiang/orca-delivery#1", BODY + b"AC-X02\n", "t1")
    with pytest.raises(DecisionRejected):
        adopt_binding(s, {"kind": "adopt_binding", "role": "issue_body", "actor": "user", "source": "chat",
                          "reuse": {"g2": "unchanged code"}})
    adopt_binding(s, {"kind": "adopt_binding", "role": "issue_body", "actor": "user", "source": "chat"})
    assert version_key(version_set(s)) != k1
    assert s["candidates"] == {}


def test_version_set_has_no_time_fields():
    vs = version_set(base_state())
    flat = repr(vs)
    assert "t0" not in flat and "observed" not in flat and "adopted_at" not in flat
