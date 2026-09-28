"""Feature state store (design §3 internal contract; later tasks only call it).

Layout under $LOOPCTL_HOME:
  features/<id>/feature.json      the only current state (canonical JSON)
  features/<id>/history/<rev>.json write-once record {revision, transition_id, prev_digest,
                                   state_digest, committed_at, state}
  features/<id>/conflicts/        rejected transition contents (feature Blocked)
  features/<id>/lock              flock for commits
  objects/<sha256 hex>            content-addressed evidence objects

History-first: a revision is committed once history/<rev>.json exists (linked write-once);
feature.json is then atomically replaced. A reader that finds history one revision ahead of
feature.json sees that newer committed revision; the next commit repairs feature.json.
"""

import contextlib
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from loopctl import clock

SCHEMA_VERSION = 1
OBJECT_KEY = "$object"
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
FEATURE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

State = dict[str, Any]


class StoreError(Exception):
    pass


class FeatureNotFound(StoreError):
    pass


class UntrustedState(StoreError):
    """Missing file, bad JSON, unknown schema, manual edit: CLI exit 5, nothing is rebuilt."""


class RevisionConflict(StoreError):
    pass


class TransitionConflict(StoreError):
    """Same transition_id already committed with different content: Blocked."""


class MissingObject(StoreError):
    pass


def home() -> Path:
    return Path(os.environ.get("LOOPCTL_HOME") or Path.home() / ".loopctl")


def _dir(feature: str) -> Path:
    if not FEATURE_ID_RE.fullmatch(feature):
        raise ValueError(f"invalid feature id {feature!r}")
    return home() / "features" / feature


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canon(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


# --- durable file primitives (atomic write + link protocol from 4ce1110 store) ---


def _fsync(fd: int) -> None:
    os.fsync(fd)
    if sys.platform == "darwin":  # APFS fsync does not flush the device cache
        with contextlib.suppress(OSError):
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        _fsync(fd)
    finally:
        os.close(fd)


def _write_tmp(directory: Path, data: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".tmp-{uuid.uuid4().hex}"
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        _fsync(fd)
    finally:
        os.close(fd)
    return tmp


def _link_history(tmp: Path, final: Path) -> None:
    os.link(tmp, final)  # fails if final exists: write-once


def _write_once(final: Path, data: bytes) -> None:
    tmp = _write_tmp(final.parent, data)
    try:
        _link_history(tmp, final)
    except FileExistsError:
        raise UntrustedState(f"history_exists:{final.name}") from None
    finally:
        tmp.unlink()
    _fsync_dir(final.parent)


def _replace_current(final: Path, data: bytes) -> None:
    tmp = _write_tmp(final.parent, data)
    os.replace(tmp, final)
    _fsync_dir(final.parent)


@contextlib.contextmanager
def _lock(d: Path) -> Iterator[None]:
    fd = os.open(d / "lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


# --- reading ---


def _record(d: Path, rev: int) -> dict[str, Any]:
    path = d / "history" / f"{rev}.json"
    if not path.exists():
        raise UntrustedState(f"history_missing:{rev}")
    try:
        rec = json.loads(path.read_bytes())
        ok = rec["revision"] == rev and digest(_canon(rec["state"])) == rec["state_digest"]
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise UntrustedState(f"history_corrupt:{rev}")
    return dict(rec)


def _read(d: Path) -> tuple[int, State, bool]:
    """(revision, state, feature.json is one committed revision behind)."""
    current = d / "feature.json"
    if not current.exists():
        raise UntrustedState("state_missing")
    raw = current.read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError:
        raise UntrustedState("state_corrupt") from None
    if not isinstance(doc, dict):
        raise UntrustedState("state_corrupt")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise UntrustedState(f"unknown_schema:{doc.get('schema_version')}")
    rev = doc.get("revision")
    if not isinstance(rev, int) or rev < 1:
        raise UntrustedState("state_corrupt")
    if _record(d, rev)["state_digest"] != digest(raw):
        raise UntrustedState("manual_edit")
    if (d / "history" / f"{rev + 1}.json").exists():
        ahead = _record(d, rev + 1)
        if ahead["prev_digest"] != digest(raw):
            raise UntrustedState(f"history_fork:{rev + 1}")
        return rev + 1, ahead["state"], True
    return rev, doc, False


def load(feature: str) -> tuple[int, State]:
    d = _dir(feature)
    if not d.is_dir():
        raise FeatureNotFound(feature)
    rev, state, _ = _read(d)
    return rev, state


def conflicts(feature: str) -> list[str]:
    """Transition ids whose conflicting content was rejected and kept (feature Blocked)."""
    c = _dir(feature) / "conflicts"
    if not c.is_dir():
        return []
    ids = {json.loads(p.read_bytes())["transition_id"] for p in c.glob("*.json")}
    return sorted(ids)


# --- committing ---


def _apply(
    pre: State | None, mutate: Callable[[State], State], rev: int, tid: str, feature: str
) -> State:
    out = mutate(copy.deepcopy(pre) if pre is not None else {})
    if not isinstance(out, dict):
        raise TypeError("mutate must return the new state dict")
    transitions = dict((pre or {}).get("transitions", {}))
    transitions[tid] = rev
    return {
        **out,
        "schema_version": SCHEMA_VERSION,
        "feature": feature,
        "revision": rev,
        "transitions": transitions,
    }


def _object_path(ref: str) -> Path:
    if not isinstance(ref, str) or not _DIGEST_RE.fullmatch(ref):
        raise MissingObject(f"not an object digest: {ref!r}")
    return home() / "objects" / ref.removeprefix("sha256:")


def _refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        if OBJECT_KEY in value:
            yield value[OBJECT_KEY]
        for v in value.values():
            yield from _refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from _refs(v)


def _check_refs(state: State) -> None:
    missing = sorted({r for r in _refs(state) if not _object_path(r).is_file()})
    if missing:
        raise MissingObject(f"state references missing objects: {missing}")


def _history_bytes(rev: int, tid: str, prev: bytes | None, state: State) -> tuple[bytes, bytes]:
    data = _canon(state)
    record = {
        "revision": rev,
        "transition_id": tid,
        "prev_digest": digest(prev) if prev is not None else None,
        "state_digest": digest(data),
        "committed_at": clock.now().isoformat(),
        "state": state,
    }
    return _canon(record), data


def _create(d: Path, tid: str, state: State) -> bool:
    """First revision: build the feature dir aside and rename it into place atomically."""
    _check_refs(state)
    record, data = _history_bytes(1, tid, None, state)
    tmp = d.parent / f".tmp-{uuid.uuid4().hex}"
    _write_once(tmp / "history" / "1.json", record)
    _replace_current(tmp / "feature.json", data)
    try:
        os.rename(tmp, d)
    except OSError:  # another process created it first
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    _fsync_dir(d.parent)
    return True


def _record_conflict(d: Path, tid: str, committed: int, attempted: State) -> None:
    data = _canon({"transition_id": tid, "committed_revision": committed, "attempted": attempted})
    name = f"{digest(tid.encode())[7:23]}-{digest(data)[7:23]}.json"
    with contextlib.suppress(UntrustedState):  # identical conflict already kept
        _write_once(d / "conflicts" / name, data)


def commit(
    feature: str,
    expected_revision: int,
    transition_id: str,
    mutate: Callable[[State], State],
) -> int:
    """Check revision, apply mutate, commit history-first. Idempotent per transition_id."""
    if not transition_id:
        raise ValueError("transition_id is required")
    d = _dir(feature)
    if not d.exists():
        if expected_revision != 0:
            raise FeatureNotFound(feature)
        if _create(d, transition_id, _apply(None, mutate, 1, transition_id, feature)):
            return 1
    with _lock(d):
        rev, state, behind = _read(d)
        if behind:
            _replace_current(d / "feature.json", _canon(state))
        if blocked := conflicts(feature):
            raise TransitionConflict(f"feature blocked by transition conflicts: {blocked}")
        done = state.get("transitions", {}).get(transition_id)
        if done is not None:
            pre = _record(d, done - 1)["state"] if done > 1 else None
            again = _apply(pre, mutate, done, transition_id, feature)
            if digest(_canon(again)) == _record(d, done)["state_digest"]:
                return int(done)
            _record_conflict(d, transition_id, done, again)
            raise TransitionConflict(transition_id)
        if rev != expected_revision:
            raise RevisionConflict(f"expected revision {expected_revision}, found {rev}")
        new = _apply(state, mutate, rev + 1, transition_id, feature)
        _check_refs(new)
        record, data = _history_bytes(rev + 1, transition_id, _canon(state), new)
        _write_once(d / "history" / f"{rev + 1}.json", record)
        _replace_current(d / "feature.json", data)
        return rev + 1


# --- evidence objects ---


def put_object(data: bytes) -> str:
    ref = digest(data)
    final = _object_path(ref)
    if not final.exists():
        tmp = _write_tmp(final.parent, data)
        try:
            os.link(tmp, final)
        except FileExistsError:
            pass
        finally:
            tmp.unlink()
        _fsync_dir(final.parent)
    return ref


def get_object(ref: str) -> bytes:
    path = _object_path(ref)
    if not path.is_file():
        raise MissingObject(ref)
    data = path.read_bytes()
    if digest(data) != ref:
        raise UntrustedState(f"object_corrupt:{ref}")
    return data


def object_ref(ref: str) -> dict[str, str]:
    """A typed evidence reference; plain digest strings (document digests) are not refs."""
    return {OBJECT_KEY: ref}
