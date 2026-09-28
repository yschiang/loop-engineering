"""`next`: the one allowed action, from the action vocabulary of design §2.

T2.1 decides by phase only. Later tasks add their own checks without reordering these
(tasks.md shared-file table: T7.1 expiry/timeouts, T5.1 correction, T6.2 publish/Pass).
T2.3 adds `safety` (readbacks and pending recovery decisions, which come before any other
action, design §2/§10) and worker dispatch for approved / implementing.
T3.1 hands over to G1 (`evidence_green` / `assess`) where dispatch has no task left.
Anything not decided here stops and hands over to a human.
"""

from typing import Any

from loopctl import assignments, clock, decisions, gates, observe, writes

State = dict[str, Any]
RECOVERY_KINDS = {**writes.RECOVERY_KINDS, **observe.RECOVERY_KINDS}


def human(blockers: list[str], decision_kinds: list[str] | None = None) -> dict[str, Any]:
    return {"action": "human", "blockers": blockers, "decision_kinds": decision_kinds or []}


def recovery_kinds(blocked: list[str]) -> list[str]:
    """The decide kinds that can clear these blockers (T2.3's recovery decisions only)."""
    kinds = {RECOVERY_KINDS[b.split(":", 1)[0]] for b in blocked if b.split(":", 1)[0] in RECOVERY_KINDS}
    return sorted(kinds)


def safety_action(state: State, blocked: list[str]) -> dict[str, Any] | None:
    if any(b.startswith("transition_conflict:") for b in blocked):
        return None
    return writes.safety(state, clock.now()) or observe.safety(state)


def next_action(state: State, blocked: list[str]) -> dict[str, Any]:
    if (first := safety_action(state, blocked)) is not None:
        return first
    if blocked:
        return human(blocked, recovery_kinds(blocked))
    if not state.get("owner"):
        return human(["unclaimed"])
    phase = state["phase"]
    if phase in ("planning", "awaiting_approval") and state.get("plan") is None:
        return human(["plan_not_registered"])
    if phase in ("planning", "awaiting_approval") and not decisions.plan_approvable(state["plan"]):
        return human(["plan_not_calibrated"])  # T2.2: a draft is registered, not approvable
    if phase in ("planning", "awaiting_approval"):
        return human(["plan_not_approved"], ["approve_plan"])
    if phase in ("approved", "implementing"):
        action = assignments.route(state, clock.now())  # T2.3: worker dispatch
        if action == human(["tasks_complete"]):
            return gates.route(state)  # T3.1: Green and G1 once every task is done
        return action
    if phase == "pass":
        return {"action": "done", "status": "pass"}
    if phase == "accepted":
        return {"action": "done", "status": "accepted"}
    return human([f"no_next_action:{phase}"])
