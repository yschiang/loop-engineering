"""External writes (design §4): the op state machine, retry and readback rules (T2.3).

T6.1 / T6.2 only add op kinds and their tool functions; the state machine stays.
"""

from datetime import datetime
from typing import Any

from loopctl.observe import Rejected

State = dict[str, Any]
KINDS = ("worktree_create", "agent_start", "prompt", "stop")




def write(feature: str, token: str | None, kind: str, op_id: str) -> dict[str, Any]:
    raise Rejected("not_implemented")  # stub (T2.3 interface)


def safety(state: State, now: datetime) -> dict[str, Any] | None:
    return None  # stub (T2.3 interface)
