"""Active time (design §10): the union of `activities` intervals and the remaining budget.

T2.3 creates the two pure functions; T7.1 extends this module (expiry stop, role timeouts,
extension effects) without changing their meaning.
"""

from datetime import datetime, timedelta
from typing import Any

State = dict[str, Any]


def active_used(state: State, now: datetime) -> timedelta:
    return timedelta(0)  # stub (T2.3 interface)


def remaining(state: State, now: datetime) -> timedelta:
    return timedelta(0)  # stub (T2.3 interface)
