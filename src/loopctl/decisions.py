"""Human decisions and native artifact registration (design §2 `register`, `decide`).

Owned only by T2.2. Interface stub; behaviour follows in the next commit.
"""

from typing import Any

State = dict[str, Any]

KINDS = (
    "approve_plan",
    "revise",
    "scope_change",
    "accept",
    "return",
    "resolve_finding",
    "waive_finding",
    "reclassify_finding",
    "resolve_operation",
    "resolve_read",
    "budget_extension",
    "policy_change",
    "handoff",
)
REGISTER_KINDS = ("plan", "binding", "policy")
PRODUCERS = ("implementer", "project_lead")
BINDING_ROLES = ("spec", "design", "ac", "sa", "skill", "baseline")


class Rejected(Exception):
    def __init__(self, error: str, **detail: Any) -> None:
        super().__init__(error)
        self.error = error
        self.detail = detail
