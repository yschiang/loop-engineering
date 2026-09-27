"""Evidence runner and baseline+overlay Red snapshot (design §6.1 v3)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Snapshot:
    commit: str
    tree: str
    parent: str
    ref: str
    included: tuple[str, ...]
    omitted_excluded: tuple[str, ...] = ()
    index_only: tuple[str, ...] = ()


@dataclass(frozen=True)
class Refusal:
    reasons: tuple[tuple[str, str], ...]  # (reason, path) - path names only, never content


@dataclass(frozen=True)
class Evidence:
    task_id: str
    attempt_id: str
    kind: str
    argv: tuple[str, ...]
    cwd: str
    status: str  # passed | test_failed | collection_error | snapshot_refused | snapshot_drift
    exit_code: int | None
    started_at: str
    ended_at: str
    stdout: bytes = b""
    stderr: bytes = b""
    failing_ids: tuple[str, ...] = ()
    snapshot: Snapshot | None = None
    refusal: Refusal | None = None
    digests: dict[str, str] = field(default_factory=dict)


def snapshot_worktree(cwd: str, t0: str, scope_paths: list[str], excludes: list[str],
                      ref: str) -> Snapshot | Refusal:
    raise NotImplementedError


def run_evidence(kind: str, task_id: str, attempt_id: str, argv: list[str], cwd: str, t0: str,
                 scope_paths: list[str], excludes: list[str]) -> Evidence:
    raise NotImplementedError
