"""Active time, role timeouts and budget extensions (design §10).

`state["activities"]` holds `{kind, attempt, start, end}` records (ISO-8601; `end` None while
running), written by the task that owns the activity. T2.3 created `active_used` (the union
of the intervals) and `remaining`; T7.1 keeps their meaning and adds:
  - `limit`: the approved active limit plus every `budget_extension active:<minutes>`;
  - the CI wait interval (T6.1 records its start): it ends when every required check is
    terminal or at the end of its window (`timeouts.ci_wait_min`, one more window from each
    `ci_wait:<H>` extension), so a timed-out wait stops counting while it is Blocked;
  - role timeouts (`timeouts.worker_attempt_min` / `review_attempt_min` from the attempt's
    start): a stop prepared at or after that deadline and confirmed marks the attempt
    timed out; a unit (task, batch, or an assignment's `unit`) gets at most
    1 + `extra_attempts_per_unit` + its `attempts:<unit>:+1` extensions timed-out attempts;
  - the stops that are due (expiry, role timeout) and the budget blockers `next` reports.
Everything is derived from recorded state (activities, attempts, writes, decisions, G3); an
extension takes effect once because decisions are keyed by id, and it only raises its own
target's limit. Nothing here writes.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from loopctl import observe

State = dict[str, Any]
ACTIVE_LIMIT = timedelta(hours=4)  # D13 (workflow.yaml budget.active_hours)
# D53: workflow.yaml `timeouts`; used when the policy is unreadable
TIMEOUTS = {"worker_attempt_min": 45.0, "review_attempt_min": 30.0, "ci_wait_min": 30.0,
            "extra_attempts_per_unit": 2.0}
ROLE_TIMEOUT = {"implementer": "worker_attempt_min", "reviewer": "review_attempt_min"}
RECOVERY_KINDS = {"active_budget_exhausted": "budget_extension", "attempt_timeout_exhausted": "budget_extension",
                  "ci_timeout": "budget_extension"}
SETTLED_PHASES = ("pass", "accepted")  # nothing left to run: no expiry or timeout routing


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def timeouts(state: State) -> dict[str, float]:
    try:
        pol = observe.policy(state)
    except observe.Rejected:
        pol = {}
    found = pol.get("timeouts")
    found = found if isinstance(found, dict) else {}
    return {k: float(found.get(k, v)) for k, v in TIMEOUTS.items()}


def extensions(state: State) -> list[dict[str, Any]]:
    found = [d for d in (state.get("decisions") or {}).values() if d.get("kind") == "budget_extension"]
    return sorted(found, key=lambda d: d["seq"])


def _extended(state: State, target: str) -> list[dict[str, Any]]:
    return [d for d in extensions(state) if d["target"] == target]


# --- active time ------------------------------------------------------------------------------


def ci_windows(state: State, activity: dict[str, Any], minutes: float) -> list[tuple[datetime, datetime]]:
    """The CI wait's windows: from its start, and from each later `ci_wait:<H>` extension."""
    start = _at(activity["start"])
    starts = [start, *(_at(d["at"]) for d in _extended(state, f"ci_wait:{activity.get('head')}") if _at(d["at"]) > start)]
    return [(s, s + timedelta(minutes=minutes)) for s in starts]


def _spans(state: State, now: datetime) -> Iterator[tuple[datetime, datetime]]:
    window: float | None = None
    for a in state.get("activities", []):
        end = _at(a["end"]) if a.get("end") else now
        if a.get("kind") != "ci_wait":
            yield _at(a["start"]), end
            continue
        window = timeouts(state)["ci_wait_min"] if window is None else window
        for start, deadline in ci_windows(state, a, window):
            yield start, min(deadline, end)


def active_used(state: State, now: datetime) -> timedelta:
    """Union of activity intervals; an unfinished activity counts up to `now`."""
    spans = sorted(_spans(state, now))
    used, reach = timedelta(0), None
    for start, end in spans:
        if reach is not None and start < reach:
            start = reach
        if end > start:
            used += end - start
            reach = end
    return used


def limit(state: State) -> timedelta:
    """The approved active limit plus every `active:<minutes>` extension (once per decision)."""
    hours = state.get("budget", {}).get("active_hours")
    base = timedelta(hours=float(hours)) if hours is not None else ACTIVE_LIMIT
    added = [int(d["target"].split(":", 1)[1]) for d in extensions(state) if d["target"].startswith("active:")]
    return base + timedelta(minutes=sum(added))


def remaining(state: State, now: datetime) -> timedelta:
    return limit(state) - active_used(state, now)


def summary(state: State, now: datetime) -> dict[str, Any]:
    used, left = active_used(state, now), remaining(state, now)
    return {"limit_s": limit(state).total_seconds(), "used_s": used.total_seconds(),
            "remaining_s": left.total_seconds(), "over_s": max(0.0, -left.total_seconds()),
            "extensions": [d["id"] for d in extensions(state)]}


# --- role timeouts ----------------------------------------------------------------------------


def unit(state: State, attempt: str) -> str:
    asg = (state.get("assignments") or {}).get(attempt) or {}
    a = (state.get("attempts") or {}).get(attempt) or {}
    return str(asg.get("unit") or asg.get("batch_id") or asg.get("task_id") or a.get("task_id"))


def deadline(state: State, attempt: str, t: dict[str, float] | None = None) -> datetime:
    a = state["attempts"][attempt]
    minutes = (t or timeouts(state))[ROLE_TIMEOUT.get(a.get("role"), "worker_attempt_min")]
    return _at(a["started_at"]) + timedelta(minutes=minutes)


def timed_out(state: State, attempt: str, t: dict[str, float] | None = None) -> bool:
    """Stopped past its role timeout: a stop prepared at or after the deadline, confirmed."""
    a = (state.get("attempts") or {}).get(attempt) or {}
    stop = (state.get("writes") or {}).get(f"{attempt}.stop") or {}
    if (a.get("end") or {}).get("evidence") != "stop_confirmed" or not stop.get("prepared_at"):
        return False
    return _at(stop["prepared_at"]) >= deadline(state, attempt, t)


def attempts_allowed(state: State, name: str, t: dict[str, float]) -> int:
    return 1 + int(t["extra_attempts_per_unit"]) + len(_extended(state, f"attempts:{name}:+1"))


def exhausted_units(state: State, t: dict[str, float]) -> list[str]:
    counts: dict[str, int] = {}
    for attempt in state.get("attempts") or {}:
        if timed_out(state, attempt, t):
            counts[unit(state, attempt)] = counts.get(unit(state, attempt), 0) + 1
    return sorted(u for u, n in counts.items() if n >= attempts_allowed(state, u, t))


# --- CI wait timeout --------------------------------------------------------------------------


def ci_timeouts(state: State, now: datetime, t: dict[str, float]) -> list[str]:
    """The head whose CI wait was not over by the end of its last window: the wait is still
    open (a check not terminal, mergeable not computed, or no required set known yet, whatever
    G3 says), or the terminal read came after it. A late read stays timed out until a
    `ci_wait:<H>` extension opens a window it falls in."""
    gs = state.get("gates") or {}
    g1, g3 = gs.get("g1") or {}, gs.get("g3") or {}
    head = g3.get("head")
    if not head or (g1.get("status"), g1.get("head")) != ("passed", head):
        return []
    for a in state.get("activities", []):
        if a.get("kind") != "ci_wait" or a.get("head") != head:
            continue
        deadline = max(end for _, end in ci_windows(state, a, t["ci_wait_min"]))
        if (not a.get("end") or _at(a["end"]) >= deadline) and now >= deadline:
            return [head]
    return []


# --- what `next` / `safety` read --------------------------------------------------------------


def blockers(state: State, now: datetime) -> list[str]:
    if state.get("phase") in SETTLED_PHASES:
        return []
    t = timeouts(state)
    out = ["active_budget_exhausted"] if remaining(state, now) <= timedelta(0) else []
    out += [f"attempt_timeout_exhausted:{u}" for u in exhausted_units(state, t)]
    return out + [f"ci_timeout:{h}" for h in ci_timeouts(state, now, t)]


def timeout_gates(state: State, now: datetime) -> dict[str, dict[str, Any]]:
    """The gates a timeout leaves without a result (design §10), shown over the recorded gate
    while its blocker holds: G2 unknown once a unit's review attempts are used up by timeouts,
    G3 unknown (`ci_timeout`, after the reasons of a G3 already unknown) once the CI wait of its
    head ran out. Recorded gates are not changed."""
    if state.get("phase") in SETTLED_PHASES:
        return {}
    t, gs, attempts = timeouts(state), state.get("gates") or {}, state.get("attempts") or {}
    reviews = [u for u in exhausted_units(state, t)
               if any(a.get("role") == "reviewer" and unit(state, k) == u for k, a in attempts.items())]
    out: dict[str, dict[str, Any]] = {}
    if reviews:
        out["g2"] = {**(gs.get("g2") or {}), "status": "unknown",
                     "reasons": [f"attempt_timeout_exhausted:{u}" for u in reviews]}
    if ci_timeouts(state, now, t):
        g3 = gs["g3"]
        kept = list(g3.get("reasons") or []) if g3.get("status") == "unknown" else []
        out["g3"] = {**g3, "status": "unknown", "reasons": [*kept, "ci_timeout"]}
    return out


def due_stops(state: State, now: datetime) -> list[str]:
    """Running attempts (agent started) to stop: all of them once the active budget is used
    up, otherwise those past their role timeout. Oldest first."""
    if state.get("phase") in SETTLED_PHASES:
        return []
    t = timeouts(state)
    expired = remaining(state, now) <= timedelta(0)
    running = sorted((a["n"], k) for k, a in (state.get("attempts") or {}).items() if not a.get("end"))
    writes = state.get("writes") or {}
    return [k for _, k in running if (writes.get(f"{k}.agent_start") or {}).get("status") == "succeeded"
            and (expired or now >= deadline(state, k, t))]
