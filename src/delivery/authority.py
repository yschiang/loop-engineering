"""Host-level feature authority locator, run lineage and feature budget (design §9.1, DR-06)."""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from delivery.store import Store, StoreError, _fsync_dir, _mkdirs_durable, _write_tmp


@dataclass
class StartOutcome:
    status: str  # created | resume | refused | blocked
    run_id: str | None = None
    state_dir: str | None = None
    repo_path: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class Budget:
    blocked: bool
    correction_rounds_used: int = 0
    active_seconds: float = 0.0
    reasons: list[str] = field(default_factory=list)


def feature_id(repo_id: str, feature_key: str) -> str:
    return hashlib.sha256(f"{repo_id}\n{feature_key}".encode()).hexdigest()


def _atomic_write_json(path: Path, body: dict[str, Any]) -> None:
    _mkdirs_durable(path.parent)
    tmp = _write_tmp(path.parent, json.dumps(body, ensure_ascii=False, indent=2).encode())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


class Authority:
    """Which run controls a repo+feature, persisted outside any clone so it survives process exit."""

    def __init__(self, state_home: Path, repo_id: str, feature_key: str) -> None:
        self.state_home = state_home
        self.repo_id = repo_id
        self.feature_key = feature_key
        self.dir = state_home / "features" / feature_id(repo_id, feature_key)
        self.path = self.dir / "authority.json"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        _mkdirs_durable(self.dir)
        fd = os.open(self.dir / "lock", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            data = json.loads(self.path.read_text()) if self.path.exists() else {
                "schema_version": 1, "repo_id": self.repo_id, "feature_key": self.feature_key,
                "active_run_id": None, "runs": []}
            yield data
        finally:
            os.close(fd)

    def _active(self, data: dict[str, Any]) -> dict[str, Any] | None:
        return next((r for r in data["runs"] if r["run_id"] == data["active_run_id"]), None)

    def start(self, repo_path: str, state_dir: str, run_id: str) -> StartOutcome:
        with self._locked() as data:
            active = self._active(data)
            if active is not None:
                if not os.path.isdir(active["state_dir"]):
                    return StartOutcome("blocked", active["run_id"], active["state_dir"], active["repo_path"],
                                        [(f"registered state_dir {active['state_dir']} is missing or unreadable;"
                                          " an abandon_run decision is required")])
                if os.path.realpath(active["repo_path"]) == os.path.realpath(repo_path):
                    return StartOutcome("resume", active["run_id"], active["state_dir"], active["repo_path"])
                return StartOutcome("refused", active["run_id"], active["state_dir"], active["repo_path"],
                                    [f"feature is controlled by run {active['run_id']} from {active['repo_path']}"])
            data["runs"].append({"run_id": run_id, "state_dir": state_dir, "repo_path": repo_path,
                                 "status": "active",
                                 "created_at": datetime.datetime.now(datetime.UTC).isoformat()})
            data["active_run_id"] = run_id
            _atomic_write_json(self.path, data)
        return StartOutcome("created", run_id, state_dir, repo_path)

    def active_run_id(self) -> str | None:
        with self._locked() as data:
            active: str | None = data["active_run_id"]
        return active

    def abandon(self, run_id: str, decision: dict[str, Any]) -> None:
        if decision.get("kind") != "abandon_run" or not decision.get("evidence") or not decision.get("actor"):
            raise ValueError("abandon requires an abandon_run decision with actor and stop/fencing evidence")
        with self._locked() as data:
            run = next(r for r in data["runs"] if r["run_id"] == run_id)
            run["status"] = "abandoned"
            run["abandon_decision"] = decision
            if data["active_run_id"] == run_id:
                data["active_run_id"] = None
            _atomic_write_json(self.path, data)

    def budget(self) -> Budget:
        with self._locked() as data:
            runs = list(data["runs"])
        total = Budget(False)
        for run in runs:
            try:
                loaded = Store(Path(run["state_dir"])).load()
            except StoreError as e:
                total.blocked = True
                total.reasons.append(f"run {run['run_id']}: {e}")
                continue
            if loaded.blocked:
                total.blocked = True
                total.reasons.extend(f"run {run['run_id']}: {r}" for r in loaded.reasons)
            used = loaded.state.get("budget", {})
            total.correction_rounds_used += int(used.get("correction_rounds_used", 0))
            total.active_seconds += float(used.get("active_seconds", 0))
        return total

    def repair_project_view(self, repo_path: str) -> Path:
        with self._locked() as data:
            view = {"schema_version": 1, "note": "view of the host authority; never authoritative",
                    "authority": str(self.path),
                    "features": {self.feature_key: {"active_run_id": data["active_run_id"],
                                                    "runs": [r["run_id"] for r in data["runs"]]}}}
        path = Path(repo_path) / ".delivery" / "project.json"
        _atomic_write_json(path, view)
        return path
