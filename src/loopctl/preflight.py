"""`loopctl preflight`: probe a worker profile of the approved policy
before anything is dispatched (design DD-3, DD-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# The envelope is cli's (DD-3). cli imports this module for its handler;
# each reads the other only once a command runs.
from loopctl import cli, native, policy, receipts, state, store

Envelope = dict[str, Any]

# The judged item of DD-1; native judges the negatives with it.
Item = native.Item


def run(key: store.Key, role: str, out: Path | None) -> tuple[int, Envelope]:
    """The steps of DD-4 for `role` in the context of the run `key`."""
    _, st = store.load(key)
    approved = approved_policy(st)
    if isinstance(approved, str):
        return cli.refusal(1, "policy_not_approved", policy=approved)
    result: dict[str, Any] = {
        "role": role,
        "verdict": "unverified",
        "receipt": None,
        "items": {},
        "versions": None,
    }
    blocked = {"kind": "preflight_unverified", "role": role, "reasons": []}
    return cli.EXIT_BLOCKED, cli.envelope(False, result, blocked=blocked)


def approved_policy(st: store.State) -> policy.Policy | str:
    """The run's policy file, read once, when a policy_change of the run
    approved the digest its bytes have now; else the status policy_view
    gives it (AC-D30). Approved means the approval, the registration and
    those bytes all have one digest."""
    registration = st["versions"]["policy"]
    if registration is None or registration.get("path") is None:
        return str(state.policy_view(st, None)["status"])
    loaded = policy.load(Path(registration["path"]))
    status = str(state.policy_view(st, loaded.digest)["status"])
    return loaded if status == "approved" else status


def current_versions(runtime: str | None) -> receipts.Versions:
    return receipts.Versions(None, None)
