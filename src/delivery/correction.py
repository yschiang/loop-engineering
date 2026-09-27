"""Correction batches, round cap, one dispute review and recurrence (design §7, D13/D25)."""

from __future__ import annotations

from typing import Any

MAX_ROUNDS = 3


def ready_for_batch(g2: dict[str, Any], g3: dict[str, Any]) -> bool:
    raise NotImplementedError


def dispatch_batch(state: dict[str, Any], version_key: str, finding_ids: list[str],
                   ci_failures: list[str], base_conflict: bool = False) -> dict[str, Any]:
    raise NotImplementedError


def check_result(batch: dict[str, Any], result: dict[str, Any]) -> list[str]:
    raise NotImplementedError


def record_recheck(state: dict[str, Any], fid: str, still_open: bool, batch_id: str, result_id: str) -> None:
    raise NotImplementedError


def reopen(state: dict[str, Any], fid: str, reviewer_basis: str) -> None:
    raise NotImplementedError


def request_dispute_review(state: dict[str, Any], fid: str, counter_evidence: str,
                           new_head: bool) -> dict[str, Any]:
    raise NotImplementedError


def settle_dispute(state: dict[str, Any], fid: str, reviewer_accepts: bool) -> dict[str, Any]:
    raise NotImplementedError
