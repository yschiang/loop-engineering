"""M-BUD b0: `budget.active_used` / `budget.remaining` over `activities` (design §10; T2.3).

The fixture state is built with the store API (validation b0); the functions are pure.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loopctl import budget, store

FEATURE = "F-1"
T0 = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "loopctl-home"
    monkeypatch.setenv("LOOPCTL_HOME", str(home))
    return home


def with_activities(*activities: dict, **fields: object) -> dict:
    store.commit(
        FEATURE, 0, "test:b0",
        lambda _: {"phase": "implementing", "activities": list(activities), "blockers": [], **fields},
    )
    return store.load(FEATURE)[1]


def test_b0_overlapping_activities_count_once(home):
    state = with_activities(
        {"kind": "worker", "attempt": "T1-a1", "start": at(0), "end": at(60)},
        {"kind": "evidence", "attempt": "T1-a1", "start": at(30), "end": at(90)},
    )
    assert budget.active_used(state, T0 + timedelta(hours=5)) == timedelta(minutes=90)


def test_b0_an_unfinished_activity_counts_up_to_now(home):
    state = with_activities(
        {"kind": "worker", "attempt": "T1-a1", "start": at(0), "end": at(20)},
        {"kind": "worker", "attempt": "T1-a2", "start": at(40), "end": None},
    )
    assert budget.active_used(state, T0 + timedelta(minutes=70)) == timedelta(minutes=50)
    assert budget.active_used(state, T0 + timedelta(minutes=100)) == timedelta(minutes=80)


def test_b0_a_blocked_period_without_activities_is_not_counted(home):
    state = with_activities(
        {"kind": "worker", "attempt": "T1-a1", "start": at(0), "end": at(30)},
        {"kind": "worker", "attempt": "T1-a2", "start": at(150), "end": at(180)},
        phase="blocked", blockers=["write_unknown:T1-a1.prompt"],
    )
    # 30 + 30 minutes of work around a two-hour Blocked gap with nothing running.
    assert budget.active_used(state, T0 + timedelta(hours=6)) == timedelta(minutes=60)


def test_b0_remaining_after_three_hours_fifty_is_ten_minutes(home):
    state = with_activities(
        {"kind": "worker", "attempt": "T1-a1", "start": at(0), "end": at(120)},
        {"kind": "review", "attempt": "R1-a1", "start": at(100), "end": at(200)},
        {"kind": "evidence", "attempt": "T1-a1", "start": at(200), "end": at(230)},
    )
    now = T0 + timedelta(hours=8)
    assert budget.active_used(state, now) == timedelta(hours=3, minutes=50)
    assert budget.remaining(state, now) == timedelta(minutes=10)
