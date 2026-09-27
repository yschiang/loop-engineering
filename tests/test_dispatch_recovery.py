"""Task 1.7 (DR-07): staged dispatch fault matrix - final stage and external call counts (AC-D06, D13, D14)."""

import pytest

from delivery.outbox import advance, new_dispatch_op
from delivery.store import Store

from .fakes import Crash, FakeRuntime

PROMPT = "implement task 2.3"


def run(tmp_path, rt, crash_expected=False):
    store = Store(tmp_path)
    if (tmp_path / "run.json").exists():
        state = store.load().state
    else:
        state = new_dispatch_op({"schema_version": 1, "operations": {}}, "op-d", "a1", PROMPT)
        store.commit(state)
    if crash_expected:
        with pytest.raises(Crash):
            advance(store, state, "op-d", runtime=rt)
        return None
    return advance(store, state, "op-d", runtime=rt)["operations"]["op-d"]


def test_crash_before_session_create_creates_exactly_once(tmp_path):
    rt = FakeRuntime(faults={"create": "crash_before"})
    run(tmp_path, rt, crash_expected=True)
    op = run(tmp_path, rt)
    assert op["stage"] == "prompt_accepted"
    assert (rt.creates, rt.sends) == (1, 1)


def test_lost_create_response_is_found_by_marker_not_recreated(tmp_path):
    rt = FakeRuntime(faults={"create": "lost"})
    op = run(tmp_path, rt)
    assert op["stage"] == "prompt_accepted"
    assert (rt.creates, rt.sends) == (1, 1)


def test_crash_after_session_created_sends_prompt_once(tmp_path):
    rt = FakeRuntime(faults={"send": "crash_before"})
    run(tmp_path, rt, crash_expected=True)
    op = run(tmp_path, rt)
    assert op["stage"] == "prompt_accepted"
    assert (rt.creates, rt.sends) == (1, 1)


def test_lost_prompt_response_with_marker_message_is_accepted_without_resend(tmp_path):
    rt = FakeRuntime(faults={"send": "lost"})
    op = run(tmp_path, rt)
    assert op["stage"] == "prompt_accepted"
    assert rt.sends == 1


def test_prompt_never_arrived_is_not_resent_to_same_session_but_fenced(tmp_path):
    rt = FakeRuntime(faults={"send": "drop"})
    op = run(tmp_path, rt)
    assert op["state"] == "fenced"
    assert op["retries_used"] == 1
    assert rt.sends == 1 and rt.stops == 1
    assert rt.sessions["s1"]["messages"] == []


def test_unconfirmed_stop_blocks(tmp_path):
    rt = FakeRuntime(faults={"send": "drop"}, stop_confirms=False)
    op = run(tmp_path, rt)
    assert op["state"] == "blocked"
    assert rt.sends == 1


def test_accepted_prompt_with_unsaved_receipt_is_recovered_from_messages(tmp_path):
    rt = FakeRuntime(faults={"send": "crash_after"})
    run(tmp_path, rt, crash_expected=True)
    op = run(tmp_path, rt)
    assert op["stage"] == "prompt_accepted"
    assert op["native_message_id"] == "m1" and op["receipt"]
    assert rt.sends == 1


def test_two_sessions_with_same_marker_block(tmp_path):
    rt = FakeRuntime(faults={"create": "crash_before"})
    run(tmp_path, rt, crash_expected=True)
    rt.sessions = {"s1": {"title": "orca-delivery attempt=a1", "messages": []},
                   "s2": {"title": "orca-delivery attempt=a1", "messages": []}}
    op = run(tmp_path, rt)
    assert op["state"] == "blocked"
    assert rt.creates == 0 and rt.sends == 0


def test_zero_sessions_without_consistent_listing_blocks(tmp_path):
    rt = FakeRuntime(faults={"create": "crash_before"}, consistent=False)
    run(tmp_path, rt, crash_expected=True)
    op = run(tmp_path, rt)
    assert op["state"] == "blocked"
    assert rt.creates == 0
