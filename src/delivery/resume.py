"""Resume: load state, check trust, recover history, converge operations, import results, re-read versions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from delivery.controller import reassess
from delivery.events import EventLog, flush_pending
from delivery.outbox import TERMINAL, advance
from delivery.results import import_result
from delivery.store import Store
from delivery.versions import version_key


def resume(run_dir: Path, github: Any, runtime: Any, assignments: dict[str, dict[str, Any]],
           read_versions: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Order (workflow-contracts): load -> trust check -> history -> operations -> results -> versions.

    Only the minimum outstanding work continues; finished tasks, findings and budget are never reset.
    """
    store = Store(run_dir)
    loaded = store.load()  # missing/corrupt/unknown schema raise: never replaced by an empty run
    if loaded.blocked:
        return {**loaded.state, "phase": "blocked",
                "blockers": [*loaded.state.get("blockers", []), {"kind": "untrusted_state", "reasons": loaded.reasons}]}
    recovered = flush_pending(store, EventLog(run_dir / "events.jsonl"))
    state = store.load().state
    if recovered.blocked:
        state["phase"] = "blocked"
        state["blockers"].append({"kind": "history_corrupt", "reasons": recovered.reasons})
        store.commit(state)
        return state
    for op_id, op in list(state["operations"].items()):
        if op["state"] not in TERMINAL:
            state = advance(store, state, op_id, github=github, runtime=runtime)
    for attempt_id, assignment in assignments.items():
        inbox = run_dir / "inbox" / attempt_id / "result.json"
        if inbox.exists():
            out = import_result(store, state, assignment, inbox)
            if out.status != "duplicate":
                state = out.state
    seen = read_versions()
    changed = version_key(seen) != version_key(state["versions"])
    if changed:
        state = reassess(state, seen)
    state.setdefault("resume_log", []).append({"seen_versions": seen, "changed": changed})
    store.commit(state)
    return state
