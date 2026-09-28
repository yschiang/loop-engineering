"""M-BUD b1–b7: active-time expiry, role timeouts and budget extensions (design §10; T7.1).

Everything goes through the public CLI in-process (`loopctl.cli.main`); `loopctl.clock.now` is
the only clock. Three environments are reused by name:
  - test_writes.Harness: fake `herdr`, real git, the T2.3 dispatch path (worker / review
    attempts, `write stop` with its process-info readback);
  - test_github.GhEnv: fake `gh`, push → PR → `observe ci` (the CI wait of T6.1);
  - test_g1.Env: the T3.1 evidence commands under a wall clock (b7).
Earlier activity (another session's work, time before a restart) is a store-API fixture of
the `activities` records T2.3 / T3.1 / T6.1 write.
"""

import sys
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from test_g1 import IMPL_DOUBLE, RED_DOUBLE, SLEEPER
from test_g1 import Env as G1Env
from test_github import GhEnv, job, run, started
from test_writes import (
    FEATURE,
    Harness,
    c_process_info,
    c_send_keys,
)

from loopctl import budget, store

MIN = timedelta(minutes=1)


@pytest.fixture
def h(tmp_path, monkeypatch, capsys, fakes) -> Harness:
    return Harness(tmp_path, monkeypatch, capsys, fakes)


@pytest.fixture
def gh(tmp_path, monkeypatch, capsys) -> GhEnv:
    return GhEnv(tmp_path, monkeypatch, capsys)


@pytest.fixture
def g1(tmp_path, monkeypatch, capsys) -> G1Env:
    return G1Env(tmp_path, monkeypatch, capsys)


# --- helpers ----------------------------------------------------------------------------------


def mutate(fn: Any) -> None:
    def apply(s: dict) -> dict:
        fn(s)
        return s

    rev, _ = store.load(FEATURE)
    store.commit(FEATURE, rev, f"test:{uuid.uuid4().hex[:8]}", apply)


def used_before(now: datetime, minutes: float, attempt: str = "T0-a1") -> None:
    """Work of an earlier session: one ended activity of `minutes` up to `now`."""
    rec = {"kind": "worker", "attempt": attempt, "start": (now - timedelta(minutes=minutes)).isoformat(),
           "end": now.isoformat()}
    mutate(lambda s: s.setdefault("activities", []).append(rec))


def add_blocker(reason: str) -> None:
    mutate(lambda s: s.setdefault("blockers", []).append(reason))


def stop(attempt: str = "T1-a1") -> dict:
    return {"action": "write", "op": "stop", "id": f"{attempt}.stop"}


def confirm_stop(h: Harness, attempt: str = "T1-a1") -> None:
    """The stop `safety` offers: keys sent (unknown), then one process-info readback."""
    op = f"{attempt}.stop"
    assert h.safety() == stop(attempt)
    h.expect(c_send_keys(attempt), c_process_info(running=False))
    code, out = h.write("stop", op)
    assert code == 0 and out["result"]["op"]["status"] == "unknown", out
    assert h.safety() == stop(attempt)  # the same op, read back
    code, out = h.write("stop", op)
    assert code == 0 and out["result"]["op"]["status"] == "succeeded", out
    assert h.state()["attempts"][attempt]["end"]["evidence"] == "stop_confirmed"


def exhaust_stop(h: Harness, attempt: str = "T1-a1") -> None:
    """Keys sent, then three process-info reads that still see the runtime."""
    op = f"{attempt}.stop"
    h.expect(c_send_keys(attempt), *[c_process_info(running=True)] * 3)
    h.write("stop", op)
    for _ in range(3):
        h.write("stop", op)
        h.clock.advance(seconds=10)
    assert f"readback_exhausted:{op}" in h.state()["blockers"]


def next_out(env: Any) -> tuple[int, dict]:
    code, out = env.cli("next", "--feature", FEATURE)
    return code, out


def agent_starts(h: Harness) -> list[str]:
    return sorted(k for k in h.state()["writes"] if k.endswith(".agent_start"))


def timed_out_fixture(attempt: str, n: int, *, role: str = "implementer", task: str | None = "T1",
                      unit: str | None = None, start: datetime, minutes: float = 45) -> None:
    """An attempt T2.3 dispatched and a stop confirmed after its role timeout (store API)."""
    prepared = start + timedelta(minutes=minutes)

    def add(s: dict) -> None:
        asg = {"attempt_id": attempt, "task_id": task, "batch_id": None, "finding_ids": [], "role": role}
        if unit:
            asg["unit"] = unit
        s.setdefault("assignments", {})[attempt] = asg
        s.setdefault("attempts", {})[attempt] = {
            "n": n, "task_id": task, "role": role, "handle": {}, "poll_s": 30, "started_at": start.isoformat(),
            "result": None, "rejected": [], "conflicts": [],
            "end": {"evidence": "stop_confirmed", "at": (prepared + MIN).isoformat()},
        }
        s.setdefault("writes", {})[f"{attempt}.stop"] = {
            "kind": "stop", "status": "succeeded", "prepared_at": prepared.isoformat(), "attempts": [], "readbacks": [],
        }
        s.setdefault("activities", []).append(
            {"kind": "review" if role == "reviewer" else "worker", "attempt": attempt, "start": start.isoformat(),
             "end": (prepared + MIN).isoformat()})

    mutate(add)


# --- b1: union, expiry stop first, offline, sessions, Blocked without activity -----------------


def test_b1_evidence_and_worker_intervals_count_once_when_overlapping_and_alone_otherwise(h):
    h.start()
    t = h.clock()
    def iso(minutes: float) -> str:
        return (t + timedelta(minutes=minutes)).isoformat()

    mutate(lambda s: s.setdefault("activities", []).extend([
        {"kind": "worker", "attempt": "T1-a1", "start": iso(0), "end": iso(40)},
        {"kind": "evidence", "attempt": "T1-a1", "evidence": "red-1", "start": iso(10), "end": iso(20)},
        {"kind": "evidence", "attempt": None, "evidence": "green-2", "start": iso(60), "end": iso(75)},
    ]))
    assert budget.active_used(h.state(), t + timedelta(hours=3)) == timedelta(minutes=55)


def test_b1_the_expiry_stop_comes_before_an_unrelated_blocker(h):
    h.start()
    used_before(h.clock(), 230)
    h.dispatch()
    add_blocker("checkout_not_removed:/tmp/elsewhere")
    h.clock.advance(minutes=9)
    code, out = next_out(h)
    assert out["next"]["action"] == "human" and h.safety() is None  # 3h59m: the blocker stops it
    h.clock.advance(minutes=1)
    assert h.next() == stop()  # 4h: the expiry stop before the other blocker
    assert h.safety() == stop()
    confirm_stop(h)
    code, out = next_out(h)
    assert code == 3, out
    assert set(out["blocked"]["reasons"]) >= {"active_budget_exhausted", "checkout_not_removed:/tmp/elsewhere"}
    assert out["next"]["action"] == "human" and "budget_extension" in out["next"]["decision_kinds"]
    calls = len(h.fakes.calls())
    code, out = h.write("agent_start", "T1-a2.agent_start")
    assert code == 3 and out["result"]["error"] == "feature_blocked", out
    assert len(h.fakes.calls()) == calls and agent_starts(h) == ["T1-a1.agent_start"]


def test_b1_a_prepared_stop_is_the_same_op_and_is_sent_once(h, monkeypatch):
    from loopctl import writes

    h.start()
    used_before(h.clock(), 235)
    h.dispatch()
    h.clock.advance(minutes=5)
    assert h.safety() == stop()

    def lost(*_: Any) -> Any:
        raise RuntimeError("process ended after prepare")

    with monkeypatch.context() as m:
        m.setattr(writes, "_call", lost)
        with pytest.raises(RuntimeError):
            h.write("stop", "T1-a1.stop")
    assert h.state()["writes"]["T1-a1.stop"]["status"] == "prepared"
    h.clock.advance(minutes=1)
    confirm_stop(h)
    assert len(h.herdr("agent", "send-keys")) == 1
    assert sorted(k for k in h.state()["writes"] if k.endswith(".stop")) == ["T1-a1.stop"]


def test_b1_an_exhausted_stop_readback_waits_for_a_human(h):
    h.start()
    used_before(h.clock(), 235)
    h.dispatch()
    h.clock.advance(minutes=5)
    assert h.safety() == stop()
    exhaust_stop(h)
    code, out = next_out(h)
    assert code == 3 and out["next"]["action"] == "human", out
    assert {"readback_exhausted:T1-a1.stop", "active_budget_exhausted"} <= set(out["next"]["blockers"])
    assert h.safety() is None  # nothing is resent on a guess
    assert h.state()["attempts"]["T1-a1"]["end"] is None and agent_starts(h) == ["T1-a1.agent_start"]


def test_b1_offline_time_is_counted_on_resume_recorded_and_blocks(h):
    h.start()
    used_before(h.clock(), 180)
    h.dispatch()
    h.clock.advance(hours=2)  # the coordinator was offline while the worker ran
    assert h.next() == stop()
    confirm_stop(h)
    code, out = h.cli("status", "--feature", FEATURE)
    assert code == 3 and "active_budget_exhausted" in out["blocked"]["reasons"], out
    over = out["result"].get("budget", {})
    assert over.get("used_s") == 5 * 3600 and over.get("over_s") == 3600, out["result"]
    assert h.next()["action"] == "human"
    assert budget.active_used(h.state(), h.clock() + timedelta(hours=3)) == timedelta(hours=5)


def test_b1_a_new_attempt_session_does_not_reset_the_budget(h):
    h.start()
    t = h.clock()
    for n, (start, end) in enumerate(((240, 160), (155, 75), (75, 5)), start=1):  # 3h50m over three sessions
        rec = {"kind": "worker", "attempt": f"T0-a{n}", "start": (t - timedelta(minutes=start)).isoformat(),
               "end": (t - timedelta(minutes=end)).isoformat()}
        mutate(lambda s, rec=rec: s.setdefault("activities", []).append(rec))
    assert budget.remaining(h.state(), t) == timedelta(minutes=10)
    h.dispatch()
    h.clock.advance(minutes=9)
    assert h.safety() is None
    h.clock.advance(minutes=1)
    assert h.safety() == stop()  # at 10 minutes of this session, not at its 45-minute timeout


def test_b1_a_blocked_period_without_open_activities_is_not_counted(h):
    h.start()
    used_before(h.clock(), 180)
    add_blocker("write_unknown:worktree")
    h.clock.advance(hours=2)
    assert budget.remaining(h.state(), h.clock()) == timedelta(hours=1)
    code, out = next_out(h)
    assert code == 3 and out["next"]["blockers"] == ["write_unknown:worktree"], out


# --- b2: worker attempt timeout (45 minutes) ---------------------------------------------------


def time_out(h: Harness, attempt: str) -> None:
    h.dispatch(attempt=attempt)
    h.clock.advance(minutes=45)
    confirm_stop(h, attempt)


def test_b2_a_a_worker_past_45_minutes_is_stopped_and_timed_out_and_a_new_attempt_follows(h):
    h.dispatch()
    h.clock.advance(minutes=44, seconds=59)
    assert h.safety() is None and h.next() != stop()
    h.clock.advance(seconds=1)
    assert h.next() == stop()
    confirm_stop(h)
    st = h.state()
    assert budget.timed_out(st, "T1-a1")
    assert h.next() == {"action": "write", "op": "agent_start", "id": "T1-a2.agent_start"}
    assert st["batches"] == {} and not any(d["kind"] == "budget_extension" for d in st["decisions"].values())


def test_b2_a_a_direct_write_at_the_role_deadline_is_refused_until_the_stop_is_confirmed(h):
    h.dispatch(until="agent_start")  # the agent runs, its prompt not sent yet
    h.clock.advance(minutes=45)
    assert h.next() == stop() and h.safety() == stop()
    calls = len(h.fakes.calls())
    code, out = h.write("prompt", "T1-a1.prompt")
    assert len(h.fakes.calls()) == calls
    assert "T1-a1.prompt" not in h.state()["writes"]  # refused before an op is prepared
    assert code == 3 and out["result"]["error"] == "feature_blocked", out
    assert out["result"]["blockers"] == ["stop_due:T1-a1"] and out["next"] == stop(), out
    confirm_stop(h)
    assert h.next() == {"action": "write", "op": "agent_start", "id": "T1-a2.agent_start"}


def test_b2_b_the_third_timeout_of_a_unit_blocks_with_zero_new_attempts(h):
    for n in (1, 2, 3):
        time_out(h, f"T1-a{n}")
    assert all(budget.timed_out(h.state(), f"T1-a{n}") for n in (1, 2, 3))
    code, out = next_out(h)
    assert code == 3, out
    assert out["next"] == {"action": "human", "blockers": ["attempt_timeout_exhausted:T1"],
                           "decision_kinds": ["budget_extension"]}
    calls = len(h.fakes.calls())
    code, out = h.write("agent_start", "T1-a4.agent_start")
    assert code == 3 and out["result"]["error"] == "feature_blocked", out
    assert len(h.fakes.calls()) == calls
    assert len(h.herdr("agent", "start")) == 3 and h.state()["batches"] == {}


def test_b2_c_an_unconfirmed_stop_blocks_and_starts_no_new_attempt(h):
    h.dispatch()
    h.clock.advance(minutes=45)
    assert h.safety() == stop()
    exhaust_stop(h)
    code, out = next_out(h)
    assert code == 3 and out["next"]["action"] == "human", out
    assert "readback_exhausted:T1-a1.stop" in out["next"]["blockers"]
    assert h.state()["attempts"]["T1-a1"]["end"] is None  # the worker stays unknown
    assert not budget.timed_out(h.state(), "T1-a1") and agent_starts(h) == ["T1-a1.agent_start"]


def test_b2_d_an_attempts_extension_allows_exactly_one_more_attempt(h):
    for n in (1, 2, 3):
        time_out(h, f"T1-a{n}")
    limit = budget.limit(h.state())
    code, out = h.decide("budget_extension", id="ext-a1", target="attempts:T1:+1", reason="flaky runner fixed")
    assert code == 0, out
    assert h.next() == {"action": "write", "op": "agent_start", "id": "T1-a4.agent_start"}
    time_out(h, "T1-a4")
    code, out = next_out(h)
    assert code == 3 and out["next"]["blockers"] == ["attempt_timeout_exhausted:T1"], out
    assert len(h.herdr("agent", "start")) == 4
    assert budget.limit(h.state()) == limit and h.state()["batches"] == {}


# --- b3: review attempt timeout (30 minutes) ---------------------------------------------------


def as_review(attempt: str, unit: str) -> None:
    def change(s: dict) -> None:
        s["attempts"][attempt]["role"] = "reviewer"
        s["assignments"][attempt].update(role="reviewer", unit=unit)
        for a in s["activities"]:
            if a.get("attempt") == attempt:
                a["kind"] = "review"

    mutate(change)


def g2_shown(h: Harness) -> dict:
    _, out = h.cli("status", "--feature", FEATURE)
    return dict(out["result"]["gates"]["g2"])


def test_b3_a_review_past_30_minutes_is_stopped_g2_stays_pending_then_unknown_when_exhausted(h):
    h.dispatch()
    as_review("T1-a1", "R1")
    h.clock.advance(minutes=29, seconds=59)
    assert h.safety() is None
    h.clock.advance(seconds=1)
    assert h.safety() == stop()
    assert g2_shown(h)["status"] == "pending"  # not failed while timing out
    confirm_stop(h)
    assert budget.timed_out(h.state(), "T1-a1")
    for n in (2, 3):
        assert g2_shown(h)["status"] == "pending"  # a new attempt may still run
        timed_out_fixture(f"R1-a{n}", n, role="reviewer", task=None, unit="R1", start=h.clock(), minutes=30)
        h.clock.advance(minutes=32)
    code, out = next_out(h)
    assert code == 3, out
    assert out["next"] == {"action": "human", "blockers": ["attempt_timeout_exhausted:R1"],
                           "decision_kinds": ["budget_extension"]}
    g2 = g2_shown(h)
    assert (g2["status"], g2["reasons"]) == ("unknown", ["attempt_timeout_exhausted:R1"]), g2
    st = h.state()
    assert "g2" not in st["gates"] and st["batches"] == {}  # G2 never failed; no correction round
    assert h.decide("budget_extension", id="ext-r1", target="attempts:R1:+1", reason="reviewer fixed")[0] == 0
    assert g2_shown(h)["status"] == "pending"  # one more review attempt may run


def test_b3_an_exhausted_worker_unit_leaves_g2_as_it_is(h):
    h.start()
    t = h.clock()
    for n in (1, 2, 3):
        timed_out_fixture(f"T1-a{n}", n, start=t + timedelta(minutes=50 * (n - 1)))
    h.clock.advance(minutes=200)
    assert h.next().get("blockers") == ["attempt_timeout_exhausted:T1"]
    assert g2_shown(h) == {"status": "pending", "reasons": ["not_evaluated"]}


# --- b4: CI wait (30 minutes) -----------------------------------------------------------------


QUEUED = {"status": "queued", "jobs": [job(status="queued")]}


def ci_timeout(gh: GhEnv) -> str:
    return f"ci_timeout:{gh.h}"


def reruns(gh: GhEnv) -> list[dict]:
    return [c for c in gh.calls() if "rerun" in " ".join(c["argv"])]


@pytest.mark.parametrize("case", ["queued", "mergeable_null"])
def test_b4_a_ci_wait_past_30_minutes_is_g3_unknown_ci_timeout_and_blocked(gh, case):
    started(gh)
    gh.open_pr(mergeable=None if case == "mergeable_null" else True)
    g3 = gh.to_g3([run(gh, **QUEUED)] if case == "queued" else [run(gh)])
    assert g3["status"] == "pending", g3
    gh.clock.advance(minutes=29, seconds=59)
    code, out = next_out(gh)
    assert code == 0 and out["next"]["action"] in ("observe", "wait"), out
    gh.clock.advance(seconds=1)
    code, out = next_out(gh)
    assert code == 3, out
    assert out["next"] == {"action": "human", "blockers": [ci_timeout(gh)], "decision_kinds": ["budget_extension"]}
    assert gh.safety() is None
    st = gh.state()
    assert reruns(gh) == [] and gh.unexpected() == [] and st["batches"] == {}


def follow(gh: GhEnv, steps: int = 8) -> dict:
    """Follow `next` (observe / wait) until it hands over; returns the last action."""
    for _ in range(steps):
        nxt = gh.next()
        if nxt["action"] == "wait":
            gh.clock.advance(seconds=nxt["poll_after_s"])
        elif nxt["action"] == "observe":
            assert gh.observe(nxt["source"])[0] == 0
        else:
            return nxt
    return gh.next()


def test_b4_an_extension_gives_one_more_window_and_a_success_then_passes(gh):
    started(gh)
    gh.open_pr()
    gh.to_g3([run(gh, **QUEUED)])
    gh.clock.advance(minutes=30)
    assert gh.next().get("blockers") == [ci_timeout(gh)]
    gh.clock.advance(minutes=5)  # the human looks at GitHub, then extends
    code, out = gh.decide("budget_extension", id="ext-ci-1", target=f"ci_wait:{gh.h}",
                          reason="runner queue drained by hand")
    assert code == 0, out
    gh.ci([run(gh)])
    assert follow(gh) == {"action": "human", "blockers": ["g3_passed"], "decision_kinds": []}
    assert gh.g3()["status"] == "passed"
    # 30 minutes of the first window, none of the 5 minutes Blocked in between
    assert budget.active_used(gh.state(), gh.clock()) == timedelta(minutes=30)
    assert reruns(gh) == [] and gh.state()["batches"] == {}


def test_b4_an_extension_is_one_window_only(gh):
    started(gh)
    gh.open_pr()
    gh.to_g3([run(gh, **QUEUED)])
    gh.clock.advance(minutes=30)
    code, out = gh.decide("budget_extension", id="ext-ci-1", target=f"ci_wait:{gh.h}", reason="retry")
    assert code == 0, out
    gh.clock.advance(minutes=29)
    code, out = next_out(gh)
    assert code == 0 and out["next"]["action"] in ("observe", "wait"), out
    gh.clock.advance(minutes=1)
    code, out = next_out(gh)
    assert code == 3 and out["next"]["blockers"] == [ci_timeout(gh)], out


@pytest.mark.parametrize("extended", [False, True])
def test_b4_a_success_read_after_the_deadline_stays_blocked_until_a_ci_wait_extension(gh, extended):
    started(gh)
    gh.open_pr()
    gh.to_g3([run(gh, **QUEUED)])
    gh.clock.advance(minutes=30)
    assert gh.next().get("blockers") == [ci_timeout(gh)]
    gh.clock.advance(minutes=1)
    gh.ci([run(gh)])
    code, out = gh.observe("ci")  # a direct read past the deadline, no extension yet
    assert code == 0, out
    assert gh.g3()["status"] == "passed"  # recorded as read
    gh.clock.advance(minutes=1)
    if extended:
        code, out = gh.decide("budget_extension", id="ext-ci-1", target=f"ci_wait:{gh.h}", reason="checked the run")
        assert code == 0, out
        assert follow(gh) == {"action": "human", "blockers": ["g3_passed"], "decision_kinds": []}
    else:
        code, out = next_out(gh)
        assert code == 3, out
        assert out["next"] == {"action": "human", "blockers": [ci_timeout(gh)], "decision_kinds": ["budget_extension"]}
    assert budget.active_used(gh.state(), gh.clock()) == timedelta(minutes=30)
    assert reruns(gh) == [] and gh.state()["batches"] == {}


# --- b5: active extension ---------------------------------------------------------------------


def test_b5_a_an_active_extension_after_expiry_allows_work_up_to_5h(h):
    h.start()
    used_before(h.clock(), 270)
    code, out = next_out(h)
    assert code == 3 and out["next"]["blockers"] == ["active_budget_exhausted"], out
    code, out = h.write("worktree_create", "worktree")
    assert code == 3 and out["result"]["error"] == "feature_blocked" and h.fakes.calls() == [], out
    code, out = h.decide("budget_extension", id="ext-1", target="active:60", reason="one more hour agreed")
    assert code == 0, out
    assert budget.limit(h.state()) == timedelta(hours=5)
    h.dispatch()
    h.clock.advance(minutes=29)
    assert h.safety() is None
    h.clock.advance(minutes=1)
    assert h.safety() == stop()  # 5h: expired again, before the 45-minute timeout


def test_b5_b_a_resent_extension_takes_effect_once(h):
    h.start()
    used_before(h.clock(), 270)
    for _ in range(2):
        code, out = h.decide("budget_extension", id="ext-1", target="active:60", reason="one more hour agreed")
        assert code == 0, out
    assert budget.limit(store.load(FEATURE)[1]) == timedelta(hours=5)  # a fresh load, as after a restart
    assert budget.remaining(h.state(), h.clock()) == timedelta(minutes=30)


def test_b5_c_an_extension_does_not_clear_an_unconfirmed_stop(h):
    h.start()
    used_before(h.clock(), 230)
    h.dispatch()
    h.clock.advance(minutes=10)
    assert h.safety() == stop()
    exhaust_stop(h)
    code, out = h.decide("budget_extension", id="ext-1", target="active:60", reason="one more hour agreed")
    assert code == 0, out
    code, out = next_out(h)
    assert code == 3 and out["next"]["action"] == "human", out
    assert "readback_exhausted:T1-a1.stop" in out["next"]["blockers"]
    assert "active_budget_exhausted" not in out["next"]["blockers"]
    assert agent_starts(h) == ["T1-a1.agent_start"]


# --- b6: attempts / ci_wait extensions: once, and only their own target ------------------------


def test_b6_attempt_extensions_apply_once_to_their_own_unit_and_clear_no_other_blocker(h):
    h.start()
    t = h.clock()
    for n in (1, 2, 3):
        timed_out_fixture(f"T1-a{n}", n, start=t + timedelta(minutes=50 * (n - 1)))
    h.clock.advance(minutes=200)
    assert h.next().get("blockers") == ["attempt_timeout_exhausted:T1"]
    code, out = h.decide("budget_extension", id="ext-t2", target="attempts:T2:+1", reason="other unit")
    assert code == 0, out
    assert h.next().get("blockers") == ["attempt_timeout_exhausted:T1"]
    for _ in range(2):
        assert h.decide("budget_extension", id="ext-t1", target="attempts:T1:+1", reason="once")[0] == 0
    assert h.next() == {"action": "write", "op": "worktree_create", "id": "worktree"}
    timed_out_fixture("T1-a4", 4, start=h.clock())
    h.clock.advance(minutes=50)
    assert h.next().get("blockers") == ["attempt_timeout_exhausted:T1"]  # one more attempt, not two
    add_blocker("readback_exhausted:T1-a4.stop")
    assert h.decide("budget_extension", id="ext-t1b", target="attempts:T1:+1", reason="again")[0] == 0
    assert h.next().get("blockers") == ["readback_exhausted:T1-a4.stop"]


def test_b6_ci_wait_extensions_apply_once_and_only_to_their_head(gh):
    started(gh)
    gh.open_pr()
    gh.to_g3([run(gh, **QUEUED)])
    gh.clock.advance(minutes=30)
    code, out = gh.decide("budget_extension", id="ext-other", target=f"ci_wait:{'d' * 40}", reason="other head")
    assert code == 0, out
    assert gh.next().get("blockers") == [ci_timeout(gh)]
    for _ in range(2):
        assert gh.decide("budget_extension", id="ext-ci-1", target=f"ci_wait:{gh.h}", reason="once")[0] == 0
    assert gh.next()["action"] in ("observe", "wait")
    gh.clock.advance(minutes=30)
    assert gh.next().get("blockers") == [ci_timeout(gh)]  # one window for the resent decision
    add_blocker("readback_exhausted:T1-a1.stop")
    assert gh.decide("budget_extension", id="ext-ci-2", target=f"ci_wait:{gh.h}", reason="again")[0] == 0
    assert gh.next().get("blockers") == ["readback_exhausted:T1-a1.stop"]


# --- b7: after an evidence command cut short by the active budget ------------------------------


def budget_cut(g1: G1Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """g15(b)'s state: 4h minus 2 s already used, the suite outlives what is left."""
    from test_writes import T0

    monkeypatch.setenv("G15_PID", str(g1.tmp / "grandchild.pid"))
    g1.wall_clock()
    g1.start(suite=[sys.executable, "-c", SLEEPER, "{junit_out}"])
    used = {"kind": "worker", "attempt": "T0-a1", "start": (T0 - timedelta(hours=4) + timedelta(seconds=2)).isoformat(),
            "end": T0.isoformat()}
    g1.mutate("budget", lambda s: {**s, "activities": [used]})


def test_b7_after_a_green_cut_by_the_active_budget_next_and_safety_hand_over(g1, monkeypatch):
    budget_cut(g1, monkeypatch)
    g1.dispatch("T1-a1")
    g1.write("src/calc.py", IMPL_DOUBLE)
    g1.commit("double")
    g1.complete("T1-a1")
    code, out = g1.green()
    assert code == 3 and out["result"]["error"] == "evidence_timeout", out
    used = budget.active_used(g1.state(), g1.clock())
    assert used >= timedelta(hours=4)
    code, out = next_out(g1)
    assert code == 3, out
    assert out["next"] == {"action": "human", "blockers": ["active_budget_exhausted"],
                           "decision_kinds": ["budget_extension"]}
    code, out = g1.cli("safety", "--feature", FEATURE)
    assert code == 3 and out["safety"] is None, out
    assert budget.active_used(g1.state(), g1.clock()) >= used  # nothing cleared
    assert not any(k.endswith(".agent_start") for k in g1.state()["writes"])


def test_b7_after_a_red_cut_by_the_active_budget_the_active_worker_is_stopped_first(g1, monkeypatch):
    budget_cut(g1, monkeypatch)
    g1.dispatch("T1-a1")
    g1.mutate("started", lambda s: s["writes"].update(
        {"T1-a1.agent_start": {"kind": "agent_start", "status": "succeeded"}}))
    g1.write("tests/test_double.py", RED_DOUBLE)
    code, out = g1.red("T1-a1")
    assert code == 3 and out["result"]["error"] == "evidence_timeout", out
    assert g1.next() == stop()
    assert g1.cli("safety", "--feature", FEATURE)[1]["safety"] == stop()
    assert budget.active_used(g1.state(), g1.clock()) >= timedelta(hours=4)
    assert sorted(k for k in g1.state()["writes"] if k.endswith(".agent_start")) == ["T1-a1.agent_start"]
