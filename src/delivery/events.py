"""events.jsonl audit history with pending-history recovery (design §8, AC-D10)."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from delivery.store import Store, StoreError, _fsync_dir, _full_fsync, _write_tmp


class EventConflict(StoreError):
    pass


@dataclass
class RecoverResult:
    blocked: bool
    reasons: list[str] = field(default_factory=list)
    diagnostic: Path | None = None


def _canon(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, ensure_ascii=False)


class EventLog:
    """Append-only audit log; run.json stays the recovery authority."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _scan(self) -> tuple[dict[str, str], int, str | None, bool]:
        """Return (id->canonical, good_length, problem, tail_only)."""
        data = self.path.read_bytes() if self.path.exists() else b""
        known: dict[str, str] = {}
        offset = 0
        segments = data.split(b"\n")
        full, tail = segments[:-1], segments[-1]
        for i, line in enumerate(full):
            try:
                event = json.loads(line)
            except ValueError:
                last_full = i == len(full) - 1 and tail == b""
                return known, offset, f"unparseable line {i + 1}", last_full
            known[str(event["id"])] = _canon(event)
            offset += len(line) + 1
        return known, offset, ("torn tail" if tail else None), True

    def recover(self) -> RecoverResult:
        _, good, problem, tail_only = self._scan()
        if problem is None:
            return RecoverResult(False)
        if not tail_only:
            return RecoverResult(True, [f"{self.path}: {problem} before end of file"])
        diag = self.path.with_name(f"{self.path.name}.corrupt-{uuid.uuid4().hex}")
        tmp = _write_tmp(self.path.parent, self.path.read_bytes())
        os.link(tmp, diag)
        tmp.unlink()
        fd = os.open(self.path, os.O_RDWR)
        try:
            os.truncate(fd, good)
            _full_fsync(fd)
        finally:
            os.close(fd)
        _fsync_dir(self.path.parent)
        return RecoverResult(False, [f"{self.path}: {problem} truncated"], diag)

    def append(self, events: list[dict[str, Any]]) -> list[str]:
        known, _, problem, _ = self._scan()
        if problem is not None:
            raise EventConflict(f"{self.path}: {problem}; recover() first")
        new: list[dict[str, Any]] = []
        for event in events:
            eid = str(event["id"])
            if eid in known:
                if known[eid] != _canon(event):
                    raise EventConflict(f"event {eid} already recorded with different content")
                continue
            known[eid] = _canon(event)
            new.append(event)
        if new:
            created = not self.path.exists()
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
            try:
                os.write(fd, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in new).encode())
                _full_fsync(fd)
            finally:
                os.close(fd)
            if created:
                _fsync_dir(self.path.parent)
        return [str(e["id"]) for e in new]


def flush_pending(store: Store, log: EventLog) -> RecoverResult:
    """Write the snapshot's pending history once, then clear it in the next snapshot."""
    loaded = store.load()
    if loaded.blocked:
        return RecoverResult(True, loaded.reasons)
    recovered = log.recover()
    if recovered.blocked:
        return recovered
    try:
        log.append(list(loaded.state.get("pending_history", [])))
    except EventConflict as e:
        return RecoverResult(True, [str(e)])
    store.commit(dict(loaded.state, pending_history=[]))
    return recovered
