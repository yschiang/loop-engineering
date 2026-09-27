"""Durable blobs, atomic run snapshots and reference integrity (design §8)."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REF_RE = re.compile(r"sha256:[0-9a-f]{64}")

SCHEMA_VERSION = 1


class StoreError(Exception):
    """Base class; every subclass means the state is not trusted and dispatch must stop."""


class StateMissing(StoreError):
    pass


class StateCorrupt(StoreError):
    pass


class SchemaMismatch(StoreError):
    pass


class BlobConflict(StoreError):
    pass


class NotDurable(StoreError):
    pass


class ManualEditDetected(StoreError):
    pass


@dataclass(frozen=True)
class BlobHandle:
    ref: str  # "sha256:<hex>"
    path: Path


@dataclass
class LoadResult:
    state: dict[str, Any]
    blocked: bool
    reasons: list[str] = field(default_factory=list)


def _full_fsync(fd: int) -> None:
    os.fsync(fd)
    if sys.platform == "darwin":  # APFS fsync does not flush the device cache
        with contextlib.suppress(OSError):
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        _full_fsync(fd)
    finally:
        os.close(fd)


def _mkdirs_durable(path: Path) -> None:
    missing: list[Path] = []
    p = path
    while not p.exists():
        missing.append(p)
        p = p.parent
    for d in reversed(missing):
        d.mkdir(exist_ok=True)
        _fsync_dir(d.parent)


def _write_tmp(directory: Path, data: bytes) -> Path:
    tmp = directory / f".tmp-{uuid.uuid4().hex}"
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        _full_fsync(fd)
    finally:
        os.close(fd)
    return tmp


def _refs(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(REF_RE.findall(value))
    if isinstance(value, dict):
        return set().union(*(_refs(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_refs(v) for v in value)) if value else set()
    return set()


class Store:
    """Single-writer store. A snapshot may only reference blobs made durable before it is committed."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._durable: set[str] = set()
        self._last_digest: str | None = None
        self._revision = 0

    @property
    def state_path(self) -> Path:
        return self.run_dir / "run.json"

    def blob_path(self, ref: str) -> Path:
        return self.run_dir / "blobs" / ref.removeprefix("sha256:")

    def put_blob(self, data: bytes, name: str | None = None) -> BlobHandle:
        digest = hashlib.sha256(data).hexdigest()
        ref = f"sha256:{digest}"
        final = self.run_dir / name if name else self.blob_path(ref)
        _mkdirs_durable(final.parent)
        tmp = _write_tmp(final.parent, data)
        try:
            try:
                os.link(tmp, final)
            except FileExistsError:
                if hashlib.sha256(final.read_bytes()).hexdigest() != digest:
                    conflict = final.with_name(f"{final.name}.conflict-{digest}")
                    with contextlib.suppress(FileExistsError):
                        os.link(tmp, conflict)
                    _fsync_dir(final.parent)
                    raise BlobConflict(f"{final} exists with different bytes; kept {conflict.name}") from None
            _fsync_dir(final.parent)
        finally:
            tmp.unlink()
            _fsync_dir(final.parent)
        if name is None:
            self._durable.add(ref)
        return BlobHandle(ref, final)

    @contextlib.contextmanager
    def _run_lock(self) -> Iterator[None]:
        _mkdirs_durable(self.run_dir)
        fd = os.open(self.run_dir / "run.lock", os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _on_disk_digest(self) -> str | None:
        p = self.state_path
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

    def commit(self, state: dict[str, Any]) -> int:
        not_durable = sorted(_refs(state) - self._durable)
        if not_durable:
            raise NotDurable(f"snapshot references blobs not made durable: {not_durable}")
        with self._run_lock():
            if self._on_disk_digest() != self._last_digest:
                raise ManualEditDetected(f"{self.state_path} changed outside this controller since last load")
            revision = self._revision + 1
            body = json.dumps(dict(state, revision=revision), ensure_ascii=False, indent=2).encode()
            tmp = _write_tmp(self.run_dir, body)
            os.replace(tmp, self.state_path)
            _fsync_dir(self.run_dir)
        self._revision = revision
        self._last_digest = hashlib.sha256(body).hexdigest()
        return revision

    def load(self) -> LoadResult:
        if not self.state_path.exists():
            raise StateMissing(str(self.state_path))
        raw = self.state_path.read_bytes()
        try:
            state = json.loads(raw)
        except ValueError as e:
            raise StateCorrupt(f"{self.state_path}: {e}") from None
        if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
            got = state.get("schema_version") if isinstance(state, dict) else type(state).__name__
            raise SchemaMismatch(f"{self.state_path}: schema_version {got!r}, expected {SCHEMA_VERSION}")
        reasons: list[str] = []
        for ref in sorted(_refs(state)):
            path = self.blob_path(ref)
            if not path.exists():
                reasons.append(f"missing blob {ref}")
            elif "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != ref:
                reasons.append(f"digest mismatch {ref}")
            else:
                self._durable.add(ref)
        self._last_digest = hashlib.sha256(raw).hexdigest()
        self._revision = int(state.get("revision", 0))
        return LoadResult(state, bool(reasons), reasons)
