"""Gates (design §7, §8). T3.1 adds G1; T6.1 (G3), T5.1 (G2) and T6.2 (Pass) add theirs
without changing the G1 rules (tasks.md shared-file table).

`route` is pure (called by `loopctl.next`); `assess` reads git and may run a diagnostic replay.
"""

from typing import Any

from loopctl.observe import Rejected

State = dict[str, Any]


def route(state: State) -> dict[str, Any]:
    """The G1 step once every approved task has a completed attempt (T3.1)."""
    return {"action": "human", "blockers": ["tasks_complete"], "decision_kinds": []}


def assess(feature: str, token: str | None) -> dict[str, Any]:
    raise Rejected("not_implemented", 1)
