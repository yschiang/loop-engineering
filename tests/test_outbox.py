"""Task 1.7: GitHub-style outbox operations - marker lookup, retry budget, unknown outcomes (AC-D12, D13, D16, F14)."""

import pytest

from delivery.outbox import advance, new_comment_op
from delivery.store import Store

from .fakes import Crash, FakeGitHub


def setup(tmp_path):
    store = Store(tmp_path)
    state = new_comment_op({"schema_version": 1, "operations": {}}, "op-1", "pr/34", "full review", "r1")
    store.commit(state)
    return store, state


def resume(tmp_path, gh):
    store = Store(tmp_path)
    return store, advance(store, store.load().state, "op-1", github=gh)


def test_response_lost_after_write_converges_without_second_post(tmp_path):
    gh = FakeGitHub(faults=["lost"])
    store, state = setup(tmp_path)
    state = advance(store, state, "op-1", github=gh)
    assert state["operations"]["op-1"]["state"] == "succeeded"
    assert len(gh.comments["pr/34"]) == 1


def test_crash_after_write_then_restart_finds_marker(tmp_path):
    gh = FakeGitHub(faults=["crash"])
    store, state = setup(tmp_path)
    with pytest.raises(Crash):
        advance(store, state, "op-1", github=gh)
    _, state = resume(tmp_path, gh)
    op = state["operations"]["op-1"]
    assert op["state"] == "succeeded" and op["receipt"]
    assert gh.posts == 1 and len(gh.comments["pr/34"]) == 1


def test_error_without_effect_is_retried_within_budget(tmp_path):
    gh = FakeGitHub(faults=["error", "error"])
    store, state = setup(tmp_path)
    state = advance(store, state, "op-1", github=gh)
    assert state["operations"]["op-1"]["state"] == "succeeded"
    assert state["operations"]["op-1"]["retries_used"] == 2
    assert len(gh.comments["pr/34"]) == 1


def test_three_failed_attempts_block_with_all_attempts_kept(tmp_path):
    gh = FakeGitHub(faults=["error", "error", "error"])
    store, state = setup(tmp_path)
    state = advance(store, state, "op-1", github=gh)
    op = state["operations"]["op-1"]
    assert op["state"] == "blocked"
    assert len(op["attempts"]) == 3 and gh.posts == 3
    assert any(b["op_id"] == "op-1" for b in state["blockers"])


def test_unknown_outcome_with_failing_lookup_blocks_without_repost(tmp_path):
    gh = FakeGitHub(faults=["lost"])
    gh.lookup_faults = ["error", "error", "error"]
    store, state = setup(tmp_path)
    state = advance(store, state, "op-1", github=gh)
    assert state["operations"]["op-1"]["state"] == "blocked"
    assert gh.posts == 1


def test_pending_op_committed_before_crash_is_executed_once_on_resume(tmp_path):
    gh = FakeGitHub()
    setup(tmp_path)  # committed pending, process died before executing it
    _, state = resume(tmp_path, gh)
    _, state = resume(tmp_path, gh)
    assert state["operations"]["op-1"]["state"] == "succeeded"
    assert gh.posts == 1
