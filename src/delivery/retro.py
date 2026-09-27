"""Retro candidate operation after human acceptance, and the P03 guard (D22/D28)."""

from __future__ import annotations

from typing import Any


def register_retro(state: dict[str, Any], acceptance: dict[str, Any]) -> str | None:
    """Register once per acceptance identity+version; replays and restarts return None (D28)."""
    marker = f"{acceptance['decision_id']}@{acceptance['version_key']}"
    if any(o["kind"] == "retro" and o["marker"] == marker for o in state["operations"].values()):
        return None
    op_id = f"op-retro-{len(state['operations']) + 1}"
    state["operations"][op_id] = {"op_id": op_id, "kind": "retro", "marker": marker, "state": "pending",
                                  "feature": acceptance["feature"], "output": "candidates_only"}
    return op_id


def may_start_trial(state: dict[str, Any], feature: str) -> bool:
    """P03-style trials start only on an explicit human start decision (D22), never implied."""
    return any(d.get("kind") == "start_trial" and d.get("actor_kind") == "human"
               and d.get("subject", {}).get("feature") == feature for d in state["decisions"])
