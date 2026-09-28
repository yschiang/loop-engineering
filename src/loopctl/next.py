"""`next`: the one allowed action, from the action vocabulary of design §2.

T2.1 decides by phase only. Later tasks add their own checks without reordering these
(tasks.md shared-file table: T7.1 expiry/timeouts, T5.1 correction, T6.2 publish/Pass).
T2.3 adds `safety` (readbacks and pending recovery decisions, which come before any other
action, design §2/§10) and worker dispatch for approved / implementing.
T3.1 hands over to G1 (`evidence_green` / `assess`) where dispatch has no task left.
T6.1 continues where G1 passed: push → pr_ensure → observe pr / ci (G3).
T7.1 puts the budget first (design §10): the stop of every running attempt once the active
budget is used up, or of an attempt past its role timeout, comes before any other safety
action or blocker; then the budget blockers (active_budget_exhausted,
attempt_timeout_exhausted:<unit>, ci_timeout:<H>) join the recorded ones.
Anything not decided here stops and hands over to a human.
"""

from datetime import datetime
from typing import Any

from loopctl import assignments, budget, clock, decisions, gates, observe, writes

State = dict[str, Any]
RECOVERY_KINDS = {**writes.RECOVERY_KINDS, **observe.RECOVERY_KINDS, **gates.RECOVERY_KINDS, **budget.RECOVERY_KINDS}


def human(blockers: list[str], decision_kinds: list[str] | None = None) -> dict[str, Any]:
    return {"action": "human", "blockers": blockers, "decision_kinds": decision_kinds or []}


def recovery_kinds(blocked: list[str]) -> list[str]:
    """The decide kinds that can clear these blockers (T2.3's recovery decisions only)."""
    kinds = {RECOVERY_KINDS[b.split(":", 1)[0]] for b in blocked if b.split(":", 1)[0] in RECOVERY_KINDS}
    return sorted(kinds)


def budget_blockers(state: State) -> list[str]:
    return budget.blockers(state, clock.now())


def write_blockers(state: State) -> list[str]:
    """What refuses a new non-stop write (design §10): the budget blockers, and every stop
    that is due, since that stop comes before any other action."""
    now = clock.now()
    return [*budget.blockers(state, now), *(f"stop_due:{a}" for a in budget.due_stops(state, now))]


def blockers(state: State, blocked: list[str]) -> list[str]:
    """The recorded blockers plus the budget's (derived from the state and the clock). The
    blocker of an op of an earlier approval is obsolete: routing supersedes that op."""
    blocked = writes.live_blockers(state, blocked)
    return [*blocked, *(b for b in budget_blockers(state) if b not in blocked)]


def _stop_step(state: State, attempt: str, now: datetime) -> dict[str, Any] | None:
    """The one step of an attempt's stop op: send it, or run the same op again (prepared,
    not delivered), or read it back; nothing once it is confirmed or Blocked."""
    op_id = f"{attempt}.stop"
    op = (state.get("writes") or {}).get(op_id)
    action = {"action": "write", "op": "stop", "id": op_id}
    if op is None or (op["status"] in ("prepared", "failed") and not op.get("blocked")):
        return action
    if op.get("blocked") or op["status"] == "succeeded":
        return None
    if op["status"] == "in_flight" and now < writes.stale_at(op):
        wait = max(1.0, (writes.stale_at(op) - now).total_seconds())
        return {"action": "wait", "poll_after_s": wait, "reason": f"write_in_flight:{op_id}"}
    return writes.safety({**state, "writes": {op_id: op}}, now)


def safety_action(state: State, blocked: list[str]) -> dict[str, Any] | None:
    if any(b.startswith("transition_conflict:") for b in blocked):
        return None
    now = clock.now()
    for attempt in budget.due_stops(state, now):  # T7.1: expiry and role-timeout stops first
        if (step := _stop_step(state, attempt, now)) is not None:
            return step
    return writes.safety(state, now) or observe.safety(state)


def next_action(state: State, blocked: list[str]) -> dict[str, Any]:
    if (first := safety_action(state, blocked)) is not None:
        return first
    blocked = blockers(state, blocked)
    if blocked:
        return human(blocked, recovery_kinds(blocked))
    if not state.get("owner"):
        return human(["unclaimed"])
    phase = state["phase"]
    if phase in ("planning", "awaiting_approval") and state.get("plan") is None:
        return human(["plan_not_registered"])
    if phase in ("planning", "awaiting_approval") and not decisions.plan_approvable(state["plan"]):
        return human(["plan_not_calibrated"])  # T2.2: a draft is registered, not approvable
    if phase in ("planning", "awaiting_approval") and (
        scope_change := decisions.superseded_by(state, state["plan"])
    ):
        # T2.2: the old contract; a revised plan must be registered before approve_plan.
        return human([f"plan_superseded:{scope_change}"])
    if phase in ("planning", "awaiting_approval"):
        return human(["plan_not_approved"], ["approve_plan"])
    if phase in ("approved", "implementing"):
        action = assignments.route(state, clock.now())  # T2.3: worker dispatch
        if action == human(["tasks_complete"]):
            action = gates.route(state)  # T3.1: Green and G1 once every task is done
            if action == human(["g1_passed"]):
                return gates.github_route(state, clock.now())  # T6.1: push, PR, CI
        return action
    if phase == "pass":
        return {"action": "done", "status": "pass"}
    if phase == "accepted":
        return {"action": "done", "status": "accepted"}
    return human([f"no_next_action:{phase}"])
