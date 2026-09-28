"""`next`: the one allowed action, from the action vocabulary of design §2.

T2.1 decides by phase only. Later tasks add their own checks without reordering these
(tasks.md shared-file table: T7.1 expiry/timeouts, T5.1 correction, T6.2 publish/Pass).
Anything not decided here stops and hands over to a human.
"""

from typing import Any

State = dict[str, Any]


def human(blockers: list[str], decision_kinds: list[str] | None = None) -> dict[str, Any]:
    return {"action": "human", "blockers": blockers, "decision_kinds": decision_kinds or []}


def next_action(state: State, blocked: list[str]) -> dict[str, Any]:
    if blocked:
        return human(blocked)
    if not state.get("owner"):
        return human(["unclaimed"])
    phase = state["phase"]
    if phase == "planning" and state.get("plan") is None:
        return human(["plan_not_registered"])
    if phase in ("planning", "awaiting_approval"):
        return human(["plan_not_approved"], ["approve_plan"])
    if phase == "pass":
        return {"action": "done", "status": "pass"}
    if phase == "accepted":
        return {"action": "done", "status": "accepted"}
    return human([f"no_next_action:{phase}"])
