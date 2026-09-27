"""Task 1.8: active interval union, crash unknown interval, limit and failure routing (AC-D16, D17)."""

import json

from delivery.budget import (
    active_seconds,
    close_activity,
    failure_route,
    may_dispatch,
    on_resume,
    open_activity,
)


def test_overlapping_worker_and_ci_count_once():
    b = {}
    open_activity(b, "w1", "worker", 0)
    open_activity(b, "ci", "ci_wait", 50)
    close_activity(b, "w1", 100)
    close_activity(b, "ci", 150)
    assert active_seconds(b, now=1000) == 150


def test_waiting_for_human_without_activity_is_not_counted():
    b = {}
    open_activity(b, "w1", "worker", 0)
    close_activity(b, "w1", 10)
    open_activity(b, "w2", "worker", 100)
    close_activity(b, "w2", 110)
    assert active_seconds(b, now=500) == 20


def test_crash_with_running_worker_counts_unknown_gap_fully():
    b = {}
    open_activity(b, "w1", "worker", 0)
    on_resume(b, last_persisted_at=100, resume_at=400, external_ends={"w1": None})
    assert active_seconds(b, now=400) == 400
    assert b["unknown_intervals"] == [[100, 400]]


def test_crash_gap_is_capped_when_every_open_activity_has_an_external_end():
    b = {}
    open_activity(b, "w1", "worker", 0)
    on_resume(b, last_persisted_at=100, resume_at=400, external_ends={"w1": 150})
    assert active_seconds(b, now=400) == 150


def test_limit_blocks_dispatch_across_restart_until_extension_decision():
    b = {}
    open_activity(b, "w1", "worker", 0)
    close_activity(b, "w1", 4 * 3600)
    assert not may_dispatch(b, now=4 * 3600 + 1)
    restarted = json.loads(json.dumps(b))  # persisted and read back after restart
    assert not may_dispatch(restarted, now=5 * 3600)
    restarted.setdefault("extensions", []).append({"decision_id": "DEC-9", "seconds": 1800})
    assert may_dispatch(restarted, now=5 * 3600)


def test_program_and_review_failures_route_to_correction_not_infra():
    assert failure_route("test_failed") == "correction"
    assert failure_route("changes_required") == "correction"
    assert failure_route("timeout") == "infra"
    assert failure_route("transport_error") == "infra"
    assert failure_route("service_unavailable") == "infra"
