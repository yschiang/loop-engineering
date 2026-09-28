"""M-OBS o1–o3: `observe worker|native` seq, read-failure budget and read time limits
(design §5). Uses the Harness from test_writes.py (fake herdr, real git, patched clock).
"""

import json
import os
import subprocess
import sys
import time

import pytest
from test_writes import (
    CLI,
    CLIENT_EXITED,
    FEATURE,
    Harness,
    assistant,
    c_agent_get,
    finished_turn,
    marker,
    tool_use,
    user,
)

from loopctl import observe

READ = "worker:T1-a1"


@pytest.fixture
def h(tmp_path, monkeypatch, capsys, fakes) -> Harness:
    return Harness(tmp_path, monkeypatch, capsys, fakes)


def failing_read() -> dict:
    """A transport failure: the herdr client exits without any answer."""
    return c_agent_get(**CLIENT_EXITED)


def fail_three_times(h: Harness, first: int) -> None:
    h.expect(*[failing_read()] * 3)
    for n in range(first, first + 3):
        code, out = h.observe("worker")
        assert h.state()["read_budget"][READ]["consecutive_failures"] == n
        if n < first + 2:
            assert (code, out["result"]["error"]) == (1, "read_failed"), out
        else:
            assert (code, out["result"]["error"]) == (3, "read_exhausted"), out
        h.clock.advance(seconds=30)


def assert_exhausted_without_fetch(h: Harness, failures: int) -> None:
    calls = len(h.fakes.calls())
    code, out = h.observe("worker")  # a new seq
    assert (code, out["result"]["error"]) == (3, "read_exhausted"), out
    restarted = subprocess.run(  # a new process: restart, another coordinator session
        [sys.executable, "-c", CLI, "observe", "worker", "--feature", FEATURE,
         f"--token={h.token}", "--attempt", "T1-a1"],
        cwd=h.repo, env=dict(os.environ), capture_output=True, text=True, check=False,
    )
    assert restarted.returncode == 3, restarted.stdout + restarted.stderr
    assert json.loads(restarted.stdout)["result"]["error"] == "read_exhausted"
    assert h.safety() is None
    nxt = h.next()
    assert nxt["action"] == "human"
    assert f"read_exhausted:{READ}" in nxt["blockers"] and "resolve_read" in nxt["decision_kinds"]
    assert len(h.fakes.calls()) == calls  # 0 automatic fetches
    assert h.state()["read_budget"][READ]["consecutive_failures"] == failures


def test_o1_read_failure_budget_survives_seq_session_and_restart(h):
    h.dispatch()
    fail_three_times(h, first=1)
    assert f"read_exhausted:{READ}" in h.state()["blockers"]
    assert_exhausted_without_fetch(h, failures=3)

    code, out = h.decide("resolve_read", id="rr-1", target=READ)
    assert code == 0, out
    assert h.safety() == {
        "action": "observe", "source": "worker", "purpose": "worker", "read_key": READ, "attempt": "T1-a1"
    }
    fail_three_times(h, first=4)  # one new allowance of three; the count is not reset
    budget = h.state()["read_budget"][READ]
    assert budget["grants"] == ["rr-1"]
    assert f"read_exhausted:{READ}" in h.state()["blockers"]
    assert_exhausted_without_fetch(h, failures=6)

    code, out = h.decide("resolve_read", id="rr-1", target=READ)  # a resend grants nothing new
    assert code == 0 and out["result"]["duplicate"] is True
    assert h.safety() is None


def test_o1_a_successful_fetch_resets_the_consecutive_count(h):
    h.dispatch()
    h.expect(failing_read(), failing_read(), c_agent_get(status="working"), failing_read())
    for expected in (1, 2, 0, 1):
        h.observe("worker")
        assert h.state()["read_budget"][READ]["consecutive_failures"] == expected
        h.clock.advance(seconds=30)
    assert f"read_exhausted:{READ}" not in h.state()["blockers"]


def test_o2_an_older_native_read_arriving_late_only_goes_to_history(h, monkeypatch):
    h.dispatch()
    h.work()
    sid, cwd = h.handle()["native_session_id"], str(h.wt)
    h.transcript([
        user(f"loopctl assignment {marker('T1-a1.prompt')}", sid, cwd),
        assistant([tool_use("tu-1")], "tool_use", sid, cwd, "a1"),
    ])
    env = h.envelope()
    original = observe.FETCHERS["native"]
    inner: dict = {}

    def late(*args, **kwargs):
        older = original(*args, **kwargs)  # this read sees the running turn…
        monkeypatch.setitem(observe.FETCHERS, "native", original)
        h.transcript(finished_turn(h, "```json\n" + json.dumps(env) + "\n```"))
        inner["code"], inner["out"] = h.observe("native")  # …a newer read commits first
        return older

    monkeypatch.setitem(observe.FETCHERS, "native", late)
    code, out = h.observe("native")

    assert inner["code"] == 0, inner["out"]
    newer = inner["out"]["result"]["seq"]
    assert code == 0, out
    assert out["result"]["outcome"] == "superseded"
    assert out["result"]["seq"] < newer
    obs = h.state()["observations"]
    current = obs["current"]["native:T1-a1"]["native"]
    assert current["seq"] == newer and current["fact"]["turn_complete"] is True
    old = [e for e in obs["history"] if e["seq"] == out["result"]["seq"]]
    assert len(old) == 1 and old[0]["superseded"] is True
    assert old[0]["fact"]["turn_complete"] is False
    assert obs["requests"][str(out["result"]["seq"])]["purpose"] == "native"
    assert h.next() == {"action": "import", "attempt": "T1-a1"}  # the newer fact stands


def test_version_watermark_older_seq_never_restores_an_old_version(h):
    h.start()
    seq_a = observe.allocate(FEATURE, "native:T1-a1", "native", "native")
    seq_b = observe.allocate(FEATURE, "native:T1-a1", "native", "native")
    for seq, head in ((seq_b, "b" * 40), (seq_a, "a" * 40)):
        observe.commit_fact(FEATURE, seq, "native:T1-a1", "native", {"found": True}, None,
                            versions={"head": head})
    state = h.state()
    assert state["versions"]["facts"]["head"] == "b" * 40
    assert state["observations"]["version_seq"] == seq_b


def test_o3_a_read_past_its_time_limit_is_killed_and_counts_as_a_transport_failure(h):
    h.dispatch()
    h.limits(read_call_s=0.5)
    late = h.tmp / "agent-get-finished"
    h.expect(c_agent_get(sleep=2.0, effects=[{"write": str(late), "text": "answered"}]))
    started = time.monotonic()
    code, out = h.observe("worker")
    assert time.monotonic() - started < 2.0
    assert (code, out["result"]["error"]) == (1, "read_failed"), out
    assert out["result"]["reason"] == "read_timeout"
    state = h.state()
    assert state["read_budget"][READ]["consecutive_failures"] == 1
    assert READ not in state["observations"]["current"]  # not taken as a successful fetch
    time.sleep(2.5)
    assert not late.exists()  # the read was terminated
