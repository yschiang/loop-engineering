"""M-DEC d3: after approval, the public CLI's `next` leads to the first assignment, which
carries the task's AC IDs and verification methods; the next task needs no new approval
(AC-O06, design §2 `next` vocabulary, §4 assignment fields).
"""

import json
import re

import pytest
from test_writes import (
    BRANCH,
    FEATURE,
    PLAN,
    TASK_ACS,
    TASK_SCOPE,
    Harness,
    c_agent_start,
    c_process_info,
    c_prompt,
    c_send_keys,
    c_worktree_create,
    finished_turn,
    marker,
)

from loopctl import store


@pytest.fixture
def h(tmp_path, monkeypatch, capsys, fakes) -> Harness:
    return Harness(tmp_path, monkeypatch, capsys, fakes)


def test_d3_first_assignment_after_approval_carries_ac_ids_and_verification(h):
    h.start()
    state = h.state()
    assert state["phase"] == "approved"
    approval_digests = state["approval"]["digests"]

    assert h.next() == {"action": "write", "op": "worktree_create", "id": "worktree"}
    h.expect(c_worktree_create(h))
    code, out = h.write("worktree_create", "worktree")
    assert code == 0, out
    assert h.state()["phase"] == "implementing"

    assert h.next() == {"action": "write", "op": "agent_start", "id": "T1-a1.agent_start"}
    h.expect(c_agent_start(h))
    code, out = h.write("agent_start", "T1-a1.agent_start")
    assert code == 0, out

    a = h.assignment("T1-a1")
    assert (a["attempt_id"], a["task_id"], a["batch_id"], a["finding_ids"]) == ("T1-a1", "T1", None, [])
    assert a["acs"] == TASK_ACS["T1"]
    assert a["scope"] == TASK_SCOPE["T1"]
    assert a["digests"] == approval_digests
    assert set(approval_digests) == {"plan", "spec"}
    assert (a["worktree"], a["branch"], a["base"], a["head"]) == (str(h.wt), BRANCH, "main", h.base_head)
    assert a["role"] == "implementer" and a["pr"] is None
    assert (a["profile"]["runtime"], a["profile"]["model"], a["profile"]["effort"]) == (
        "claude-code", "claude-opus-5-5", "high"
    )
    assert a["result_path"] == str(h.wt / ".loopctl" / "results" / "T1-a1.json")
    assert a["plan"] == {"locator": PLAN, "version": "v1", "digest": approval_digests["plan"]}

    assert h.next() == {"action": "write", "op": "prompt", "id": "T1-a1.prompt"}
    h.expect(c_prompt())
    code, out = h.write("prompt", "T1-a1.prompt")
    assert code == 0, out
    text = h.herdr("agent", "prompt")[0][3]
    assert marker("T1-a1.prompt") in text
    handed = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    assert handed is not None and json.loads(handed.group(1)) == a  # the hand-off is the assignment
    for ac in TASK_ACS["T1"]:
        assert ac["id"] in text and ac["verify"] in text

    # The worker finishes T1; the next task is dispatched without another approval.
    t1_head = h.work()
    env = h.envelope()
    h.put_result(env)
    assert h.next() == {"action": "import", "attempt": "T1-a1"}
    code, out = h.import_result()
    assert code == 0, out
    h.transcript(finished_turn(h, json.dumps(env)))
    nxt = h.next()
    assert (nxt["action"], nxt["source"], nxt["read_key"]) == ("observe", "native", "native:T1-a1")
    code, out = h.observe("native")
    assert code == 0, out
    assert h.next() == {"action": "write", "op": "stop", "id": "T1-a1.stop"}  # free the pane
    h.expect(c_send_keys(), c_process_info(running=False))
    assert h.write("stop", "T1-a1.stop")[0] == 0
    assert h.write("stop", "T1-a1.stop")[0] == 0

    assert h.next() == {"action": "write", "op": "agent_start", "id": "T2-a1.agent_start"}
    h.expect(c_agent_start(h, "T2-a1"))
    code, out = h.write("agent_start", "T2-a1.agent_start")
    assert code == 0, out
    a2 = h.assignment("T2-a1")
    assert (a2["task_id"], a2["acs"], a2["head"]) == ("T2", TASK_ACS["T2"], t1_head)
    assert [d["kind"] for d in h.state()["decisions"].values()] == ["approve_plan"]
    assert h.unexpected() == []


@pytest.mark.parametrize("plan", ["no_task_block", "empty_tasks", "task_without_acs"])
def test_an_approved_plan_without_a_usable_task_list_dispatches_nothing(h, plan):
    text = (h.repo / PLAN).read_text()
    head, _, _ = text.partition("```loopctl-plan")
    block = {
        "no_task_block": "",
        "empty_tasks": f"```loopctl-plan\nworkspace: {{source: {h.repo}, worktree: {h.wt}, "
                       f"branch: {BRANCH}, base: main}}\ntasks: []\n```\n",
        "task_without_acs": f"```loopctl-plan\nworkspace: {{source: {h.repo}, worktree: {h.wt}, "
                            f"branch: {BRANCH}, base: main}}\ntasks: [{{id: T1, acs: [], scope: [src/x.py]}}]\n```\n",
    }[plan]
    (h.repo / PLAN).write_text(head + block)
    h.start()
    nxt = h.next()
    assert nxt["action"] == "human" and nxt["blockers"] == ["plan_tasks_unusable"]
    rev = h.revision()
    code, out = h.write("worktree_create", "worktree")
    assert (code, out["result"]["error"]) == (1, "not_routable"), out
    assert h.revision() == rev and h.fakes.calls() == []
    assert store.load(FEATURE)[1]["writes"] == {}
