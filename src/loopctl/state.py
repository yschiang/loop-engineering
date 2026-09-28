"""Feature state shape (design §3), owner token and the read-only status view.

Each later task adds its own top-level fields; schema_version lives in store.
"""

import hashlib
import hmac
from typing import Any

State = dict[str, Any]
GATES = ("g1", "g2", "g3")
_NOT_EVALUATED = {"status": "pending", "reasons": ["not_evaluated"]}


def new_feature(repo: str, repo_id: str, issue: str) -> State:
    return {
        "repo": repo,
        "repo_id": repo_id,
        "issue": issue,
        "phase": "planning",
        "owner": None,
        "plan": None,
        "approval": None,
        "versions": {},
        "attempts": {},
        "writes": {},
        "observations": {},
        "read_budget": {},
        "gates": {},
        "findings": {},
        "batches": {},
        "budget": {},
        "decisions": {},
        "acceptance": None,
        "blockers": [],
    }


def token_digest(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()


def is_owner(state: State, token: str | None) -> bool:
    """Writing commands check `--token` against the stored digest (design §3)."""
    owner = state.get("owner")
    if not owner or not token:
        return False
    return hmac.compare_digest(str(owner["token_digest"]), token_digest(token))


def blockers(state: State, transition_conflicts: list[str]) -> list[str]:
    return [*state.get("blockers", []), *(f"transition_conflict:{t}" for t in transition_conflicts)]


def view(state: State, blocked: list[str]) -> dict[str, Any]:
    owner = state.get("owner")
    return {
        "feature": state["feature"],
        "phase": state["phase"],
        "owner": {"actor": owner["actor"]} if owner else None,
        "gates": {g: state.get("gates", {}).get(g) or _NOT_EVALUATED for g in GATES},
        "blockers": blocked,
    }


def render_human(v: dict[str, Any], revision: int, next_: dict[str, Any]) -> str:
    owner = v["owner"]["actor"] if v["owner"] else "unclaimed"
    lines = [
        f"feature: {v['feature']} (revision {revision})",
        f"phase: {v['phase']}",
        f"owner: {owner}",
        "gates:",
        *(
            f"  {g}: {gate['status']} ({', '.join(gate.get('reasons') or []) or '-'})"
            for g, gate in v["gates"].items()
        ),
        f"blockers: {', '.join(v['blockers']) or 'none'}",
        "next: " + next_["action"] + "".join(
            f"; {k}: {', '.join(map(str, val)) if isinstance(val, list) else val}"
            for k, val in next_.items()
            if k != "action" and val
        ),
    ]
    return "\n".join(lines)
