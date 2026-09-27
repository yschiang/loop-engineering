"""Import worker results from the inbox into durable, write-once storage (AC-D05, D07, D08)."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from delivery.store import Store


@dataclass
class ImportOutcome:
    status: str  # imported | duplicate | conflict | rejected
    state: dict[str, Any]
    ref: str | None = None
    reasons: list[str] = field(default_factory=list)


def _in_scope(path: str, scope: list[str]) -> bool:
    return any(path == s or path.startswith(s.rstrip("/") + "/") for s in scope)


def _identity_problems(body: Any, assignment: dict[str, Any]) -> list[str]:
    if not isinstance(body, dict):
        return ["result is not a JSON object"]
    problems = [f"{k}: result {body.get(k)!r} != assignment {assignment[k]!r}"
                for k in ("run_id", "task_id", "attempt_id") if body.get(k) != assignment[k]]
    observed = body.get("observed") or {}
    if observed.get("cwd") != assignment["clone_path"]:
        problems.append(f"observed.cwd: {observed.get('cwd')!r} != {assignment['clone_path']!r}")
    if observed.get("base") != assignment["base_sha"]:
        problems.append(f"observed.base: {observed.get('base')!r} != {assignment['base_sha']!r}")
    outside = [p for p in body.get("changed_paths", []) if not _in_scope(p, assignment["scope"]["paths"])]
    if outside:
        problems.append(f"scope: paths outside assignment scope {outside}")
    return problems


def import_result(store: Store, state: dict[str, Any], assignment: dict[str, Any], inbox_file: Path) -> ImportOutcome:
    """Persist the original bytes first, then decide; never overwrite an imported result."""
    raw = inbox_file.read_bytes()
    ref = store.put_blob(raw).ref
    new = copy.deepcopy(state)
    attempt = assignment["attempt_id"]
    try:
        problems = _identity_problems(json.loads(raw), assignment)
    except ValueError as e:
        problems = [f"unparseable result: {e}"]
    if problems:
        new.setdefault("rejected_results", []).append({"attempt_id": attempt, "ref": ref, "reasons": problems})
        return ImportOutcome("rejected", new, ref, problems)
    existing = state.get("imported_results", {}).get(attempt)
    if existing == ref:
        return ImportOutcome("duplicate", state, ref)
    if existing is not None:
        reason = f"attempt {attempt} already imported as {existing}; new bytes {ref}"
        new.setdefault("blockers", []).append({"kind": "result_conflict", "attempt_id": attempt,
                                               "refs": [existing, ref], "reason": reason})
        return ImportOutcome("conflict", new, ref, [reason])
    new.setdefault("imported_results", {})[attempt] = ref
    return ImportOutcome("imported", new, ref)
