"""Active time (design §10): the union of `activities` intervals and the remaining budget.

`state["activities"]` holds `{kind, attempt, start, end}` records (ISO-8601; `end` None while
running), written by the task that owns the activity. T2.3 creates the two pure functions;
T7.1 extends this module (expiry stop, role timeouts, extension effects) without changing
their meaning.
"""

from datetime import datetime, timedelta
from typing import Any

State = dict[str, Any]
ACTIVE_LIMIT = timedelta(hours=4)  # D13 (workflow.yaml budget.active_hours)


def active_used(state: State, now: datetime) -> timedelta:
    """Union of activity intervals; an unfinished activity counts up to `now`."""
    spans = sorted(
        (datetime.fromisoformat(a["start"]), datetime.fromisoformat(a["end"]) if a.get("end") else now)
        for a in state.get("activities", [])
    )
    used, reach = timedelta(0), None
    for start, end in spans:
        if reach is not None and start < reach:
            start = reach
        if end > start:
            used += end - start
            reach = end
    return used


def limit(state: State) -> timedelta:
    """The approved active limit; T7.1 adds applied `active` extensions here."""
    hours = state.get("budget", {}).get("active_hours")
    return timedelta(hours=float(hours)) if hours is not None else ACTIVE_LIMIT


def remaining(state: State, now: datetime) -> timedelta:
    return limit(state) - active_used(state, now)


def timed_out(state: State, attempt: str) -> bool:
    """T7.1: the attempt was stopped past its role timeout (interface only)."""
    return False
