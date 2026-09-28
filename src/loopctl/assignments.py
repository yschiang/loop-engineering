"""Assignments, the common result envelope and `result import` (design §4, §6, §8; T2.3).

T5.1 only adds `review` / `correction` entries to BODY_VALIDATORS.
"""

from typing import Any

from loopctl.observe import Rejected

State = dict[str, Any]




def import_result(feature: str, token: str | None, attempt: str, file: str | None) -> dict[str, Any]:
    raise Rejected("not_implemented")  # stub (T2.3 interface)
