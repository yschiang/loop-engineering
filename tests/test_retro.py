"""Task 2.13: one Retro candidate operation per acceptance identity; P03 not started implicitly (AC-O14, O15)."""

import json

from delivery.retro import may_start_trial, register_retro

ACC = {"decision_id": "DEC-accept-1", "version_key": "vk:abc", "feature": "S1"}


def test_repeated_or_replayed_acceptance_registers_one_retro_operation():
    s = {"operations": {}, "decisions": []}
    first = register_retro(s, ACC)
    assert register_retro(s, dict(ACC)) is None
    restarted = json.loads(json.dumps(s))
    assert register_retro(restarted, ACC) is None
    ops = [o for o in restarted["operations"].values() if o["kind"] == "retro"]
    assert [o["op_id"] for o in ops] == [first]
    assert ops[0]["marker"] == "DEC-accept-1@vk:abc"
    assert ops[0]["output"] == "candidates_only"


def test_new_version_acceptance_gets_its_own_retro():
    s = {"operations": {}, "decisions": []}
    a = register_retro(s, ACC)
    b = register_retro(s, {**ACC, "decision_id": "DEC-accept-2", "version_key": "vk:def"})
    assert a != b and b is not None


def test_p03_is_not_started_without_an_explicit_user_start_decision():
    s = {"operations": {}, "decisions": [{"kind": "accept", "subject": {"feature": "P03"}}]}
    assert may_start_trial(s, "P03") is False
    s["decisions"].append({"kind": "start_trial", "actor_kind": "human", "subject": {"feature": "P03"}})
    assert may_start_trial(s, "P03") is True
